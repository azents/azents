{{- if and .Values.runtimeProviderKubernetes.enabled .Values.runtimeProviderKubernetes.pdb.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: azents-runtime-provider-kubernetes
  namespace: {{ include "azents.runtimeProviderKubernetesNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
spec:
  maxUnavailable: {{ .Values.runtimeProviderKubernetes.pdb.maxUnavailable }}
  selector:
    matchLabels:
      {{- include "azents.selectorLabels" (dict "root" . "component" "runtime-provider-kubernetes") | nindent 6 }}
{{- end }}
