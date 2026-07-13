{{- if .Values.web.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "azents.webConfigMapName" . | quote }}
  namespace: {{ include "azents.webNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "web") | nindent 4 }}
data:
  {{- range $key, $value := .Values.web.env }}
  {{ $key }}: {{ $value | quote }}
  {{- end }}
  PUBLIC_API_URL: {{ include "azents.apiserverPublicUrl" . | quote }}
  INTERNAL_API_URL: {{ include "azents.apiserverInternalUrl" . | quote }}
  ADMIN_WEB_URL: {{ .Values.web.adminWebUrl | quote }}
{{- end }}
