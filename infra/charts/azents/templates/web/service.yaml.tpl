{{- if .Values.web.enabled }}
apiVersion: v1
kind: Service
metadata:
  name: web
  namespace: {{ include "azents.webNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "web") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
spec:
  selector:
    app.kubernetes.io/name: {{ include "azents.name" . | quote }}
    app.kubernetes.io/instance: {{ .Release.Name | quote }}
    app.kubernetes.io/component: "web"
  ports:
    - name: http
      port: 3000
      targetPort: 3000
  type: ClusterIP
{{- end }}
