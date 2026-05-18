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
{{- default (printf "%s-secret" (include "openldap.fullname" .)) .Values.secret.existingSecret -}}
{{- end -}}

{{- define "openldap.tlsSecretName" -}}
{{- default (printf "%s-tls" (include "openldap.fullname" .)) .Values.bootstrap.tls.existingSecret -}}
{{- end -}}

{{- define "openldap.preUpgradeImage" -}}
{{- $repository := default .Values.image.repository .Values.preUpgrade.image.repository -}}
{{- $tag := default .Values.image.tag .Values.preUpgrade.image.tag -}}
{{- printf "%s:%s" $repository $tag -}}
{{- end -}}

{{- define "openldap.replicationHost" -}}
{{- $root := index . 0 -}}
{{- $ordinal := index . 1 -}}
{{- printf "%s://%s-%d.%s-headless.%s.svc.cluster.local:%v" $root.Values.bootstrap.replication.scheme (include "openldap.fullname" $root) $ordinal (include "openldap.fullname" $root) $root.Release.Namespace $root.Values.bootstrap.replication.port -}}
{{- end -}}

{{- define "openldap.replicationHosts" -}}
{{- if .Values.bootstrap.replication.hosts -}}
{{- join " " .Values.bootstrap.replication.hosts -}}
{{- else -}}
{{- $hosts := list -}}
{{- range $i := until (int .Values.replicaCount) -}}
{{- $hosts = append $hosts (include "openldap.replicationHost" (list $ $i)) -}}
{{- end -}}
{{- join " " $hosts -}}
{{- end -}}
{{- end -}}

{{- define "openldap.replicationEnabled" -}}
{{- $mode := .Values.bootstrap.replication.mode -}}
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

{{- define "openldap.podUrls" -}}
{{- printf "ldap://$(POD_NAME).$(HEADLESS_SERVICE_NAME).$(POD_NAMESPACE).svc.cluster.local:%v ldaps://$(POD_NAME).$(HEADLESS_SERVICE_NAME).$(POD_NAMESPACE).svc.cluster.local:%v ldapi:///" .Values.containerPorts.ldap .Values.containerPorts.ldaps -}}
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
