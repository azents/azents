{{- $hosts := .Values.server.apiserver.ingress.hosts }}
{{- if and .Values.server.enabled .Values.server.apiserver.enabled (or .Values.ingress.enabled .Values.server.apiserver.ingress.enabled) $hosts }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: apiserver
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "apiserver") | nindent 4 }}
  {{- $annotations := merge (dict) .Values.ingress.annotations .Values.server.apiserver.ingress.annotations }}
  {{- with $annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  {{- $className := default .Values.ingress.className .Values.server.apiserver.ingress.className }}
  {{- if $className }}
  ingressClassName: {{ $className | quote }}
  {{- end }}
  {{- $tls := default .Values.ingress.tls .Values.server.apiserver.ingress.tls }}
  {{- with $tls }}
  tls:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  rules:
    {{- range $hosts }}
    - host: {{ .host | quote }}
      http:
        paths:
          - path: {{ default "/" .path | quote }}
            pathType: {{ default "Prefix" .pathType | quote }}
            backend:
              service:
                name: apiserver
                port:
                  number: 8010
    {{- end }}
{{- end }}
