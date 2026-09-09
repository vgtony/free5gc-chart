{{/* UERANSIM resource names and labels. */}}
{{- define "ueransim.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ueransim.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := include "ueransim.name" . -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "ueransim.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | quote }}
app.kubernetes.io/name: {{ include "ueransim.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
project: {{ .Values.global.projectName }}
{{- end -}}

{{- define "ueransim.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ueransim.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "ueransim.networkAttachmentName" -}}
{{- if .Values.network.existingNad -}}
{{- .Values.network.existingNad -}}
{{- else -}}
{{- printf "%s-%s" .Values.network.name (include "ueransim.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/* Preserve explicit names; otherwise isolate managed credentials per release. */}}
{{- define "ueransim.authSecretName" -}}
{{- if .Values.ue.existingAuthSecret -}}
{{- .Values.ue.existingAuthSecret -}}
{{- else if .Values.ue.auth.create -}}
{{- printf "%s-ue-auth" (include "ueransim.fullname" . | trunc 55 | trimSuffix "-") -}}
{{- else -}}
{{- fail "ue.existingAuthSecret is required when ue.auth.create=false; create that Secret in the release namespace with keys key and op" -}}
{{- end -}}
{{- end -}}
