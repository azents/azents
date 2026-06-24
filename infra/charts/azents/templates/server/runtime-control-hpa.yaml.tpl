{{- if and .Values.server.enabled .Values.server.runtimeControl.enabled .Values.server.runtimeControl.autoscaling.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: runtime-control
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-control") | nindent 4 }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: runtime-control
  minReplicas: {{ .Values.server.runtimeControl.autoscaling.minReplicas }}
  maxReplicas: {{ .Values.server.runtimeControl.autoscaling.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{ .Values.server.runtimeControl.autoscaling.targetCPUUtilizationPercentage }}
{{- end }}
