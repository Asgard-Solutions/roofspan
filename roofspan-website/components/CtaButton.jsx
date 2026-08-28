"use client";
import { trackEvent } from "../src/analytics";

// A CTA link that fires an analytics event on click (no-op when analytics is not configured).
export default function CtaButton({ href, label, event = "product_cta_click", params = {}, className = "btn-primary", testid, children }) {
  return (
    <a
      href={href}
      className={className}
      data-testid={testid}
      onClick={() => trackEvent(event, { link_url: href, link_text: label || (typeof children === "string" ? children : undefined), ...params })}
    >
      {children || label}
    </a>
  );
}
