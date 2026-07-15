export function OmirynLogo() {
  const logoSrc = `${import.meta.env.BASE_URL}assets/omiryn-logo-neon.png`;

  return (
    <div className="brand-lockup" aria-label="Omiryn">
      <img src={logoSrc} alt="" />
    </div>
  );
}
