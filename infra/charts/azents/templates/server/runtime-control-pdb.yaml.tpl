{{- if and .Values.server.enabled .Values.server.runtimeControl.enabled .Values.server.runtimeControl.pdb.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: runtime-control
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-control") | nindent 4 }}
spec:
  minAvailable: {{ .Values.server.runtimeControl.pdb.minAvailable }}
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "azents.name" . | quote }}
      app.kubernetes.io/instance: {{ .Release.Name | quote }}
      app.kubernetes.io/component: "runtime-control"
{{- end }}
