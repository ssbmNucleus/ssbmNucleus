import './BrandLogo.css'
// Header mark. Always the Nucleus logo — stats mode is the same brand (the
// wordmark grows a superscript "stats" tag instead of swapping marks).

export default function BrandLogo() {
  return (
    <span className="header-logo brand-logo" aria-hidden="true">
      <img className="brand-logo-image" src="./nucleuslogo.svg" alt="" />
    </span>
  )
}
