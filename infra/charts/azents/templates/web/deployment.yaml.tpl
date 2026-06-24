{{- if .Values.web.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  namespace: {{ include "azents.webNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "web") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "azents.name" . | quote }}
      app.kubernetes.io/instance: {{ .Release.Name | quote }}
      app.kubernetes.io/component: "web"
  template:
    metadata:
      labels:
        {{- include "azents.componentLabels" (dict "root" . "component" "web") | nindent 8 }}
        app.kubernetes.io/part-of: "azents"
        {{- with .Values.global.podLabels }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      {{- with .Values.global.podAnnotations }}
      annotations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
    spec:
      serviceAccountName: {{ include "azents.webServiceAccountName" . | quote }}
      {{- with .Values.global.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      containers:
        - name: web
          image: {{ include "azents.webImage" . | quote }}
          imagePullPolicy: {{ .Values.web.image.pullPolicy | quote }}
          ports:
            - name: http
              containerPort: 3000
          envFrom:
            - configMapRef:
                name: {{ include "azents.webConfigMapName" . | quote }}
          readinessProbe:
            httpGet:
              path: /
              port: 3000
            initialDelaySeconds: 5
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          {{- with .Values.web.resources }}
          resources:
            {{- toYaml . | nindent 12 }}
          {{- end }}
{{- end }}
