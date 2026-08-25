# free5GC on Kubernetes

Tested with Ubuntu 24.04, Kubernetes 1.36, containerd, Flannel, Helm 3.21.3,
Multus thick plugin, free5GC v3.3.0, and `gtp5g` v0.8.10.

Run the **All nodes** sections on every control-plane and worker node. Run the
remaining sections on the control-plane node unless stated otherwise.

## 1. Prepare every node

```bash
sudo swapoff -a
sudo sed -i '/ swap / s/^/#/' /etc/fstab

cat <<'EOF_MODULES' | sudo tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF_MODULES
sudo modprobe overlay
sudo modprobe br_netfilter

cat <<'EOF_SYSCTL' | sudo tee /etc/sysctl.d/99-kubernetes-cri.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF_SYSCTL
sudo sysctl --system

sudo apt-get update
sudo apt-get install -y containerd curl gpg git
sudo mkdir -p /etc/containerd
containerd config default | sudo tee /etc/containerd/config.toml >/dev/null
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
sudo systemctl enable --now containerd

sudo mkdir -p -m 755 /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.36/deb/Release.key | \
  sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
printf '%s\n' 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.36/deb/ /' | \
  sudo tee /etc/apt/sources.list.d/kubernetes.list
sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl
```

## 2. Create the cluster

On the control-plane node:

```bash
sudo kubeadm init --pod-network-cidr=10.244.0.0/16
mkdir -p "$HOME/.kube"
sudo cp /etc/kubernetes/admin.conf "$HOME/.kube/config"
sudo chown "$(id -u):$(id -g)" "$HOME/.kube/config"
kubectl apply -f https://github.com/flannel-io/flannel/releases/download/v0.28.8/kube-flannel.yml
kubeadm token create --print-join-command
```

Run the printed `sudo kubeadm join ...` command on every worker. Then verify:

```bash
kubectl get nodes
kubectl get pods -A
```

## 3. Install Helm and cluster prerequisites

```bash
curl -fsSL -o /tmp/get-helm-3 https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
chmod 700 /tmp/get-helm-3
sudo /tmp/get-helm-3 --version v3.21.3

kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.36/deploy/local-path-storage.yaml
kubectl rollout status -n local-path-storage deployment/local-path-provisioner --timeout=2m
kubectl patch storageclass local-path -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'

kubectl apply -f https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/6386911021ffb0715b930a2d372f2aa16084e78f/deployments/multus-daemonset-thick.yml
kubectl rollout status -n kube-system daemonset/kube-multus-ds --timeout=3m
```

Confirm every relevant node has `macvlan`, `ipvlan`, `static`, and `tuning` in
`/opt/cni/bin`.

## 4. Install gtp5g on every UPF node

The bundled UPF rejects gtp5g 0.9.x and newer. Install the pinned version on each
node that can run a UPF:

```bash
sudo apt-get update
sudo apt-get install -y gcc make git linux-headers-"$(uname -r)"
git clone --branch v0.8.10 --depth 1 https://github.com/free5gc/gtp5g.git /tmp/gtp5g
make -C /tmp/gtp5g
sudo make -C /tmp/gtp5g install
sudo depmod -a
sudo modprobe gtp5g
echo gtp5g | sudo tee /etc/modules-load.d/gtp5g.conf
modinfo -F version gtp5g
rm -rf /tmp/gtp5g
```

The final command must print `0.8.10`.

## 5. Install free5GC

```bash
git clone --branch free5gc-chart --single-branch https://github.com/vgtony/free5gc-chart.git
cd free5gc-chart
```

The chart defaults to the three-UPF ULCL topology. OSM does not need to label the
worker nodes: required pod anti-affinity automatically places the three UPFs on
different hosts. The cluster therefore needs at least three schedulable workers,
each with the `gtp5g` module, Multus plugins, and an `eth0` interface connected to
the configured `10.160.101.0/24` network. Override `global.*network.masterIf` when
the common worker interface has another name.

Validate and install:

```bash
helm lint .
helm template free5gc . -n free5gc >/tmp/free5gc.yaml
kubectl create namespace free5gc --dry-run=client -o yaml | kubectl apply -f -
kubectl apply --dry-run=server -f /tmp/free5gc.yaml
helm upgrade --install free5gc . -n free5gc \
  --timeout 10m --wait
```

Verify:

```bash
kubectl get pods -n free5gc
helm status free5gc -n free5gc
kubectl logs -n free5gc deployment/free5gc-free5gc-amf-amf | grep 'Listen on .*:38412'
kubectl logs -n free5gc deployment/free5gc-free5gc-smf-smf | grep 'setup association'
```

All workloads should be `1/1 Running`; SMF should associate with all configured
UPFs.
