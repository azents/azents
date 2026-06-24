{{- $hosts := .Values.web.ingress.hosts }}
{{- if and .Values.web.enabled (or .Values.ingress.enabled .Values.web.ingress.enabled) $hosts }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web
  namespace: {{ include "azents.webNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "web") | nindent 4 }}
  {{- $annotations := merge (dict) .Values.ingress.annotations .Values.web.ingress.annotations }}
  {{- with $annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  {{- $className := default .Values.ingress.className .Values.web.ingress.className }}
  {{- if $className }}
  ingressClassName: {{ $className | quote }}
  {{- end }}
  {{- $tls := default .Values.ingress.tls .Values.web.ingress.tls }}
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
                name: web
                port:
                  number: 3000
    {{- end }}
{{- end }}
