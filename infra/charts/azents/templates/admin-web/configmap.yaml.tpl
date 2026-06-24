{{- if .Values.adminWeb.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "azents.adminWebConfigMapName" . | quote }}
  namespace: {{ include "azents.adminWebNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "admin-web") | nindent 4 }}
data:
  {{- range $key, $value := .Values.adminWeb.env }}
  {{ $key }}: {{ $value | quote }}
  {{- end }}
  ADMIN_API_URL: {{ include "azents.adminserverUrl" . | quote }}
{{- end }}
