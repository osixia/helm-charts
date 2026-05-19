{{- define "phpldapadmin.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "phpldapadmin.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "phpldapadmin.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "phpldapadmin.labels" -}}
helm.sh/chart: {{ include "phpldapadmin.chart" . }}
app.kubernetes.io/name: {{ include "phpldapadmin.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "phpldapadmin.selectorLabels" -}}
app.kubernetes.io/name: {{ include "phpldapadmin.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "phpldapadmin.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "phpldapadmin.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "phpldapadmin.secretName" -}}
{{- default (include "phpldapadmin.fullname" .) .Values.app.existingSecret -}}
{{- end -}}

{{/*
Auto-generate APP_KEY and keep it stable across upgrades using lookup.
Returns existing key if the secret already exists, otherwise generates a new one.
*/}}
{{- define "phpldapadmin.appKey" -}}
{{- if .Values.app.appKey -}}
{{- .Values.app.appKey -}}
{{- else if .Values.app.existingSecret -}}
{{- "" -}}
{{- else -}}
{{- $secretName := include "phpldapadmin.fullname" . -}}
{{- $existing := lookup "v1" "Secret" .Release.Namespace $secretName -}}
{{- if $existing -}}
{{- index $existing.data "APP_KEY" | b64dec -}}
{{- else -}}
{{- randAlphaNum 32 | b64enc | printf "base64:%s" -}}
{{- end -}}
{{- end -}}
{{- end -}}
