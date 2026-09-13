{{- $gateway := .Values.server.runtimeWebGateway }}
{{- if and .Values.server.enabled $gateway.enabled }}
apiVersion: v1
kind: Service
metadata:
  name: runtime-web-gateway
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-web-gateway") | nindent 4 }}
spec:
  selector:
    app.kubernetes.io/name: {{ include "azents.name" . | quote }}
    app.kubernetes.io/instance: {{ .Release.Name | quote }}
    app.kubernetes.io/component: "runtime-web-gateway"
  ports:
    - name: http
      port: 80
      targetPort: http
  type: ClusterIP
{{- end }}
