{{- if and .Values.server.enabled .Values.server.adminserver.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: adminserver
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "adminserver") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "azents.name" . | quote }}
      app.kubernetes.io/instance: {{ .Release.Name | quote }}
      app.kubernetes.io/component: "adminserver"
  template:
    metadata:
      labels:
        {{- include "azents.componentLabels" (dict "root" . "component" "adminserver") | nindent 8 }}
        app.kubernetes.io/part-of: "azents"
        {{- with .Values.global.podLabels }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      {{- with .Values.global.podAnnotations }}
      annotations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
    spec:
      serviceAccountName: {{ include "azents.serverServiceAccountName" . | quote }}
      {{- with .Values.global.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      containers:
        - name: adminserver
          image: {{ include "azents.serverImage" . | quote }}
          imagePullPolicy: {{ .Values.server.image.pullPolicy | quote }}
          command: ["./bin/adminserver.sh"]
          ports:
            - name: http
              containerPort: 8011
          envFrom:
            - configMapRef:
                name: {{ include "azents.serverConfigMapName" . | quote }}
          env:
            - name: AZ_ADMIN_PORT
              value: "8011"
            {{- include "azents.serverAuthSecretEnv" . | nindent 12 }}
            {{- include "azents.externalServiceSecretEnv" . | nindent 12 }}
          readinessProbe:
            httpGet:
              path: /health/v1/readiness
              port: 8011
            initialDelaySeconds: 5
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          {{- with .Values.server.adminserver.resources }}
          resources:
            {{- toYaml . | nindent 12 }}
          {{- end }}
{{- end }}
