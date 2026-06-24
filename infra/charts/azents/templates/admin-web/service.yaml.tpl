{{- if .Values.adminWeb.enabled }}
apiVersion: v1
kind: Service
metadata:
  name: admin-web
  namespace: {{ include "azents.adminWebNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "admin-web") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
spec:
  selector:
    app.kubernetes.io/name: {{ include "azents.name" . | quote }}
    app.kubernetes.io/instance: {{ .Release.Name | quote }}
    app.kubernetes.io/component: "admin-web"
  ports:
    - name: http
      port: 3000
      targetPort: 3000
  type: ClusterIP
{{- end }}
