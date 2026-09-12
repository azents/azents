{{- $gateway := .Values.server.runtimeWebGateway }}
{{- if and .Values.server.enabled $gateway.enabled $gateway.pdb.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: runtime-web-gateway
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-web-gateway") | nindent 4 }}
spec:
  maxUnavailable: {{ $gateway.pdb.maxUnavailable }}
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "azents.name" . | quote }}
      app.kubernetes.io/instance: {{ .Release.Name | quote }}
      app.kubernetes.io/component: "runtime-web-gateway"
{{- end }}
