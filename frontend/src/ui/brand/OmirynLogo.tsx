export function OmirynLogo() {
  const logoSrc = `${import.meta.env.BASE_URL}assets/omiryn-logo-neon.png`;

  return (
    <a className="brand-lockup" href="/app" aria-label="Omiryn home">
      <img src={logoSrc} alt="" />
    </a>
  );
}
