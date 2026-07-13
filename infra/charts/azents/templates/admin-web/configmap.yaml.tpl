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
  PUBLIC_BASE_URL: {{ include "azents.adminWebPublicUrl" . | quote }}
  INTERNAL_PUBLIC_API_URL: {{ include "azents.adminWebPublicApiUrl" . | quote }}
  INTERNAL_ADMIN_API_URL: {{ include "azents.adminserverUrl" . | quote }}
  PUBLIC_WEB_URL: {{ include "azents.adminWebPublicWebUrl" . | quote }}
{{- end }}
