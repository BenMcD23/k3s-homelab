{{- /* Tailnet device names. pv- groups them in the Tailscale admin console;
     the resolver keeps the slug short enough for the longest one to fit 63. */ -}}
{{- define "stack.host" -}}pv-{{ required "slug" .root.Values.slug }}-{{ .part }}{{- end -}}
{{- define "stack.url" -}}https://{{ include "stack.host" . }}.{{ .root.Values.tailnet }}{{- end -}}

{{- define "stack.labels" -}}
app.kubernetes.io/part-of: preview-stack
preview.317atc.co.uk/branch: {{ .Values.slug | quote }}
{{- end -}}

{{- /* Everything a person uses lives on home (ADR 0004), and the preview
     images are amd64-only. */ -}}
{{- define "stack.podSpec" -}}
nodeSelector:
  role: interactive
# Below everything else on home: under memory pressure these go first, and
# prod pods failing over from squadron can preempt them.
priorityClassName: preview
securityContext:
  runAsNonRoot: true
{{- end -}}

{{- /* Its own name on the tailnet, and nowhere else: no Funnel. These run the
     dev sign-in, which makes anyone who reaches them the owner. */ -}}
{{- define "stack.ingress" -}}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ .part }}
  namespace: pv-{{ .root.Values.slug }}
  labels:
    {{- include "stack.labels" .root | nindent 4 }}
spec:
  ingressClassName: tailscale
  defaultBackend:
    service:
      name: {{ .part }}
      port:
        number: {{ .port }}
  tls:
    - hosts:
        - {{ include "stack.host" . }}
{{- end -}}
