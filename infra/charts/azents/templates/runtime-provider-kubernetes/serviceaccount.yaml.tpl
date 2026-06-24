{{- if and .Values.runtimeProviderKubernetes.enabled .Values.runtimeProviderKubernetes.serviceAccount.create }}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "azents.runtimeProviderKubernetesServiceAccountName" . | quote }}
  namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
{{- end }}
