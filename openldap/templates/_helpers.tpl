{{/*
Expand the name of the chart.
*/}}
{{- define "openldap.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "openldap.fullname" -}}
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

{{- define "openldap.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "openldap.labels" -}}
helm.sh/chart: {{ include "openldap.chart" . }}
app.kubernetes.io/name: {{ include "openldap.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "openldap.selectorLabels" -}}
app.kubernetes.io/name: {{ include "openldap.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "openldap.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "openldap.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "openldap.secretName" -}}
{{- default (printf "%s-secret" (include "openldap.fullname" .)) .Values.extraEnvSecret.existingSecret -}}
{{- end -}}

{{- define "openldap.bootstrapEnvSecretName" -}}
{{- printf "%s-bootstrap-env-secret" (include "openldap.fullname" .) -}}
{{- end -}}

{{- define "openldap.tlsSecretName" -}}
{{- default (printf "%s-tls" (include "openldap.fullname" .)) .Values.tlsSecret.existingSecret -}}
{{- end -}}

{{- define "openldap.preUpgradeImage" -}}
{{- $repository := default .Values.image.repository .Values.previousImage.repository -}}
{{- $tag := default .Values.image.tag .Values.previousImage.tag -}}
{{- printf "%s:%s" $repository $tag -}}
{{- end -}}

{{- define "openldap.replicationHost" -}}
{{- $root := index . 0 -}}
{{- $ordinal := index . 1 -}}
{{- $protocol := $root.Values.openldap.bootstrap.replication.protocol -}}
{{- $port := ternary $root.Values.openldap.protocols.ldaps.port $root.Values.openldap.protocols.ldap.port (eq $protocol "ldaps") -}}
{{- printf "%s://%s-%d.%s-headless.%s.svc.%s:%v" $protocol (include "openldap.fullname" $root) $ordinal (include "openldap.fullname" $root) $root.Release.Namespace $root.Values.clusterDomain $port -}}
{{- end -}}

{{- define "openldap.replicationHosts" -}}
{{- if .Values.openldap.bootstrap.replication.hosts -}}
{{- join " " .Values.openldap.bootstrap.replication.hosts -}}
{{- else -}}
{{- $hosts := list -}}
{{- range $i := until (int .Values.replicaCount) -}}
{{- $hosts = append $hosts (include "openldap.replicationHost" (list $ $i)) -}}
{{- end -}}
{{- join " " $hosts -}}
{{- end -}}
{{- end -}}

{{- define "openldap.replicationEnabled" -}}
{{- $mode := .Values.openldap.bootstrap.replication.mode -}}
{{- if eq $mode "enabled" -}}
true
{{- else if eq $mode "disabled" -}}
false
{{- else if eq $mode "auto" -}}
{{- if gt (int .Values.replicaCount) 1 -}}true{{- else -}}false{{- end -}}
{{- else -}}
{{- fail "bootstrap.replication.mode must be one of: auto, enabled, disabled" -}}
{{- end -}}
{{- end -}}

{{- define "openldap.urls" -}}
{{- $urls := list -}}
{{- if .Values.openldap.protocols.ldap.enabled -}}
{{- $urls = append $urls (printf "ldap://:%v" .Values.openldap.protocols.ldap.port) -}}
{{- end -}}
{{- if .Values.openldap.protocols.ldaps.enabled -}}
{{- $urls = append $urls (printf "ldaps://:%v" .Values.openldap.protocols.ldaps.port) -}}
{{- end -}}
{{- if .Values.openldap.protocols.ldapi.enabled -}}
{{- $urls = append $urls "ldapi:///" -}}
{{- end -}}
{{- join " " $urls -}}
{{- end -}}

{{- define "openldap.podUrls" -}}
{{- $urls := list -}}
{{- if .Values.openldap.protocols.ldap.enabled -}}
{{- $urls = append $urls (printf "ldap://$(POD_NAME).$(HEADLESS_SERVICE_NAME).$(POD_NAMESPACE).svc.%s:%v" .Values.clusterDomain .Values.openldap.protocols.ldap.port) -}}
{{- end -}}
{{- if .Values.openldap.protocols.ldaps.enabled -}}
{{- $urls = append $urls (printf "ldaps://$(POD_NAME).$(HEADLESS_SERVICE_NAME).$(POD_NAMESPACE).svc.%s:%v" .Values.clusterDomain .Values.openldap.protocols.ldaps.port) -}}
{{- end -}}
{{- if .Values.openldap.protocols.ldapi.enabled -}}
{{- $urls = append $urls "ldapi:///" -}}
{{- end -}}
{{- join " " $urls -}}
{{- end -}}

{{- define "openldap.podAntiAffinity" -}}
{{- if eq .Values.podAntiAffinity.type "required" }}
podAntiAffinity:
  requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels:
          {{- include "openldap.selectorLabels" . | nindent 10 }}
      topologyKey: {{ .Values.podAntiAffinity.topologyKey | quote }}
{{- else }}
podAntiAffinity:
  preferredDuringSchedulingIgnoredDuringExecution:
    - weight: {{ .Values.podAntiAffinity.weight }}
      podAffinityTerm:
        labelSelector:
          matchLabels:
            {{- include "openldap.selectorLabels" . | nindent 12 }}
        topologyKey: {{ .Values.podAntiAffinity.topologyKey | quote }}
{{- end }}
{{- end -}}
