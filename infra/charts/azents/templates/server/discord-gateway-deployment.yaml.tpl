{{- if and .Values.server.enabled .Values.server.discordGateway.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: discord-gateway
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "discord-gateway") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "azents.name" . | quote }}
      app.kubernetes.io/instance: {{ .Release.Name | quote }}
      app.kubernetes.io/component: "discord-gateway"
  template:
    metadata:
      labels:
        {{- include "azents.componentLabels" (dict "root" . "component" "discord-gateway") | nindent 8 }}
        app.kubernetes.io/part-of: "azents"
    spec:
      terminationGracePeriodSeconds: 60
      serviceAccountName: {{ include "azents.serverServiceAccountName" . | quote }}
      containers:
        - name: discord-gateway
          image: {{ include "azents.serverImage" . | quote }}
          imagePullPolicy: {{ .Values.server.image.pullPolicy | quote }}
          command: ["./bin/discordgatewayworker.sh"]
          envFrom:
            - configMapRef:
                name: {{ include "azents.serverConfigMapName" . | quote }}
          env:
            - name: AZ_WORKER_HEALTH_PORT
              value: "8013"
            {{- include "azents.serverAuthSecretEnv" . | nindent 12 }}
            {{- include "azents.platformGitHubAppSecretEnv" . | nindent 12 }}
            {{- include "azents.externalServiceSecretEnv" . | nindent 12 }}
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8013
          readinessProbe:
            httpGet:
              path: /readyz
              port: 8013
          {{- with .Values.server.discordGateway.resources }}
          resources:
            {{- toYaml . | nindent 12 }}
          {{- end }}
{{- end }}
