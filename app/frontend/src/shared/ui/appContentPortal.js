export const getAppContentPortalTarget = () => (
  typeof document !== 'undefined'
    ? document.querySelector('.app-content')
    : null
)
