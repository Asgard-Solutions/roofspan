import Script from "next/script";
import { GA_MEASUREMENT_ID, GTM_ID } from "../src/analytics";

// Injects GA4 (gtag) and/or GTM only when the corresponding env var is set. No IDs are hard-coded.
export default function Analytics() {
  return (
    <>
      {GA_MEASUREMENT_ID ? (
        <>
          <Script src={`https://www.googletagmanager.com/gtag/js?id=${GA_MEASUREMENT_ID}`} strategy="afterInteractive" />
          <Script id="ga4-init" strategy="afterInteractive" dangerouslySetInnerHTML={{ __html:
            `window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}window.gtag=gtag;gtag('js',new Date());gtag('config','${GA_MEASUREMENT_ID}');` }} />
        </>
      ) : null}
      {GTM_ID ? (
        <Script id="gtm-init" strategy="afterInteractive" dangerouslySetInnerHTML={{ __html:
          `window.dataLayer=window.dataLayer||[];(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src='https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);})(window,document,'script','dataLayer','${GTM_ID}');` }} />
      ) : null}
    </>
  );
}
