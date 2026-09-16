FROM golang:1.25.5-bookworm AS build
WORKDIR /src
RUN git clone https://github.com/free5gc/go-upf.git . && git checkout 4474dc86cf7f9851283d4c1895f0b61356b7711e
COPY n9-destination-match.patch /tmp/n9.patch
RUN git apply /tmp/n9.patch
COPY n9_compat_test.go internal/forwarder/n9_compat_test.go
RUN go test -short ./internal/forwarder
RUN CGO_ENABLED=0 go build -trimpath -o /out/upf ./cmd
FROM docker.io/towards5gs/free5gc-upf@sha256:09ac580458cf960168d390224afa650bd0e6d9b3b534859e973b12f5708b7829
COPY --from=build /out/upf /free5gc/upf/upf
LABEL org.opencontainers.image.revision="4474dc86cf7f9851283d4c1895f0b61356b7711e+n9-compat"
