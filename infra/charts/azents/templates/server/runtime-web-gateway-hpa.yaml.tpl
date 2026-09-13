{{- $gateway := .Values.server.runtimeWebGateway }}
{{- if and .Values.server.enabled $gateway.enabled $gateway.autoscaling.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: runtime-web-gateway
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-web-gateway") | nindent 4 }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: runtime-web-gateway
  minReplicas: {{ $gateway.autoscaling.minReplicas }}
  maxReplicas: {{ $gateway.autoscaling.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{ $gateway.autoscaling.targetCPUUtilizationPercentage }}
{{- end }}
