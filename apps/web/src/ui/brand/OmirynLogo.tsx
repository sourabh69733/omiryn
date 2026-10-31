export function OmirynLogo() {
  const markSrc = `${import.meta.env.BASE_URL}assets/omiryn-mark.svg`;

  return (
    <div className="brand-lockup" aria-label="Omiryn">
      <img src={markSrc} alt="" />
      <span aria-hidden="true">Omiryn</span>
    </div>
  );
}
