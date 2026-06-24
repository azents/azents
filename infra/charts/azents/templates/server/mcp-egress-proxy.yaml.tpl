{{- if .Values.server.mcpEgressProxy.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: mcp-egress-proxy-config
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "mcp-egress-proxy") | nindent 4 }}
data:
  squid.conf: |
    acl k8s_api dstdomain .eks.amazonaws.com
    acl k8s_api dstdomain .azmk8s.io
{{- range .Values.server.mcpEgressProxy.privateCidrs }}
    acl blocked_nets dst {{ . }}
{{- end }}
    acl blocked_nets dst fc00::/7
    http_access allow k8s_api
    http_access deny blocked_nets
    http_access allow all
    http_port 3128
    access_log stdio:/var/log/squid/access.log
    cache_log /var/log/squid/cache.log
    cache deny all
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-egress-proxy
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "mcp-egress-proxy") | nindent 4 }}
spec:
  selector:
    matchLabels:
      {{- include "azents.selectorLabels" (dict "root" . "component" "mcp-egress-proxy") | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "azents.componentLabels" (dict "root" . "component" "mcp-egress-proxy") | nindent 8 }}
    spec:
      containers:
        - name: squid
          image: {{ include "azents.mcpEgressProxyImage" . | quote }}
          imagePullPolicy: {{ .Values.server.mcpEgressProxy.image.pullPolicy | quote }}
          ports:
            - containerPort: 3128
          volumeMounts:
            - name: config
              mountPath: /etc/squid/squid.conf
              subPath: squid.conf
          readinessProbe:
            tcpSocket:
              port: 3128
            initialDelaySeconds: 2
            periodSeconds: 5
          {{- with .Values.server.mcpEgressProxy.resources }}
          resources:
            {{- toYaml . | nindent 12 }}
          {{- end }}
      volumes:
        - name: config
          configMap:
            name: mcp-egress-proxy-config
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-egress-proxy
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "mcp-egress-proxy") | nindent 4 }}
spec:
  selector:
    {{- include "azents.selectorLabels" (dict "root" . "component" "mcp-egress-proxy") | nindent 4 }}
  ports:
    - port: 3128
      targetPort: 3128
{{- if .Values.server.mcpEgressProxy.networkPolicy.enabled }}
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: mcp-egress-proxy-egress
  namespace: {{ include "azents.serverNamespace" . | quote }}
  labels:
    {{- include "azents.componentLabels" (dict "root" . "component" "mcp-egress-proxy") | nindent 4 }}
spec:
  podSelector:
    matchLabels:
      {{- include "azents.selectorLabels" (dict "root" . "component" "mcp-egress-proxy") | nindent 6 }}
  policyTypes:
    - Egress
  egress:
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except:
              {{- toYaml .Values.server.mcpEgressProxy.privateCidrs | nindent 14 }}
    - ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
{{- end }}
{{- end }}
