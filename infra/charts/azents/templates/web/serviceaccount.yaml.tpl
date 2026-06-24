{{- if and .Values.web.enabled .Values.web.serviceAccount.create }}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "azents.webServiceAccountName" . | quote }}
  namespace: {{ include "azents.webNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "web") | nindent 4 }}
{{- end }}
