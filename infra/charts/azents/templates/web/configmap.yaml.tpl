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
  RUNTIME_WEB_GATEWAY_ENABLED: {{ .Values.server.runtimeWebGateway.enabled | quote }}
  RUNTIME_WEB_GATEWAY_AUTH_MODE: {{ .Values.server.runtimeWebGateway.authMode | quote }}
  RUNTIME_WEB_GATEWAY_MAIN_WEB_ORIGIN: {{ .Values.server.runtimeWebGateway.mainWebOrigin | quote }}
  RUNTIME_WEB_GATEWAY_BROKER_ORIGIN: {{ .Values.server.runtimeWebGateway.brokerOrigin | quote }}
  RUNTIME_WEB_GATEWAY_COOKIE_DOMAIN: {{ .Values.server.runtimeWebGateway.cookieDomain | quote }}
  RUNTIME_WEB_GATEWAY_IDENTITY_COOKIE_NAME: {{ .Values.server.runtimeWebGateway.identityCookieName | quote }}
{{- end }}
