{{- if and .Values.server.enabled .Values.server.apiserver.enabled }}
apiVersion: v1
kind: Service
metadata:
  name: apiserver
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "apiserver") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
spec:
  selector:
    app.kubernetes.io/name: {{ include "azents.name" . | quote }}
    app.kubernetes.io/instance: {{ .Release.Name | quote }}
    app.kubernetes.io/component: "apiserver"
  ports:
    - name: http
      port: 8010
      targetPort: 8010
  type: ClusterIP
---
{{- end }}
{{- if and .Values.server.enabled .Values.server.runtimeControl.enabled }}
apiVersion: v1
kind: Service
metadata:
  name: runtime-control
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "runtime-control") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
spec:
  selector:
    app.kubernetes.io/name: {{ include "azents.name" . | quote }}
    app.kubernetes.io/instance: {{ .Release.Name | quote }}
    app.kubernetes.io/component: "runtime-control"
  ports:
    - name: grpc
      port: 8030
      targetPort: grpc
  type: ClusterIP
---
{{- end }}
{{- if and .Values.server.enabled .Values.server.adminserver.enabled }}
apiVersion: v1
kind: Service
metadata:
  name: adminserver
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "adminserver") | nindent 4 }}
    app.kubernetes.io/part-of: "azents"
spec:
  selector:
    app.kubernetes.io/name: {{ include "azents.name" . | quote }}
    app.kubernetes.io/instance: {{ .Release.Name | quote }}
    app.kubernetes.io/component: "adminserver"
  ports:
    - name: http
      port: 8011
      targetPort: 8011
  type: ClusterIP
---
{{- end }}
