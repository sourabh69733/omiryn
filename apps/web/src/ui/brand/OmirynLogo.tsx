export function OmirynLogo() {
  const markSrc = `${import.meta.env.BASE_URL}assets/omiryn-mark.svg`;
  const markDarkSrc = `${import.meta.env.BASE_URL}assets/omiryn-mark-dark.svg`;

  return (
    <div className="brand-lockup" aria-label="Omiryn">
      <picture>
        <source srcSet={markDarkSrc} media="(prefers-color-scheme: dark)" />
        <img src={markSrc} alt="" />
      </picture>
      <span aria-hidden="true">Omiryn</span>
    </div>
  );
}
