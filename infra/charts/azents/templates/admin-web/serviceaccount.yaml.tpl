{{- if and .Values.adminWeb.enabled .Values.adminWeb.serviceAccount.create }}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "azents.adminWebServiceAccountName" . | quote }}
  namespace: {{ include "azents.adminWebNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "admin-web") | nindent 4 }}
{{- end }}
