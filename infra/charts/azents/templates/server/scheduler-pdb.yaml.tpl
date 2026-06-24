{{- if and .Values.server.enabled .Values.server.scheduler.enabled .Values.server.scheduler.pdb.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: scheduler
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "scheduler") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
spec:
  maxUnavailable: {{ .Values.server.scheduler.pdb.maxUnavailable }}
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "azents.name" . | quote }}
      app.kubernetes.io/instance: {{ .Release.Name | quote }}
      app.kubernetes.io/component: "scheduler"
{{- end }}
