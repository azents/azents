import Script from "next/script";

interface GoogleAnalyticsProps {
  measurementId: string;
}

export function GoogleAnalytics({
  measurementId,
}: GoogleAnalyticsProps): React.ReactElement {
  const serializedMeasurementId = JSON.stringify(measurementId);

  return (
    <>
      <Script
        src={`https://www.googletagmanager.com/gtag/js?id=${measurementId}`}
        strategy="afterInteractive"
      />
      <Script
        id="google-analytics"
        strategy="afterInteractive"
        dangerouslySetInnerHTML={{
          __html: `
window.dataLayer = window.dataLayer || [];
function gtag(){window.dataLayer.push(arguments);}
gtag('js', new Date());
gtag('config', ${serializedMeasurementId});
`,
        }}
      />
    </>
  );
}
