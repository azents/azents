{{- if .Values.server.enabled }}
{{- $providers := list }}
{{- if .Values.runtimeProviderKubernetes.enabled }}
{{- $providerNamespace := include "azents.runtimeProviderKubernetesNamespace" . }}
{{- $providerServiceAccountName := include "azents.runtimeProviderKubernetesServiceAccountName" . }}
{{- $providers = append $providers (dict
  "declarationKey" "runtime-provider-kubernetes"
  "providerId" .Values.runtimeProviderKubernetes.providerId
  "kind" "kubernetes"
  "initial" (dict
    "displayName" "Kubernetes"
    "enabled" true
    "availabilityMode" "platform_wide"
    "setAsPlatformDefaultWhenUnset" true
  )
  "authentication" (dict
    "method" "kubernetes_service_account"
    "subject" (printf "system:serviceaccount:%s:%s" $providerNamespace $providerServiceAccountName)
    "namespace" $providerNamespace
    "serviceAccountName" $providerServiceAccountName
    "audience" "azents-runtime-control"
  )
) }}
{{- end }}
{{- $digest := toJson $providers | sha256sum }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "azents.runtimeProviderBootstrapConfigMapName" . | quote }}
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-bootstrap") | nindent 4 }}
data:
  providers.yaml: |
    apiVersion: azents.io/v1
    source:
      key: {{ printf "helm/%s/%s" .Release.Namespace .Release.Name | quote }}
      revision: {{ $digest | quote }}
      digest: {{ $digest | quote }}
    providers:{{ $providers | toYaml | nindent 6 }}
{{- end }}
