import { getAnimDisplayName, getAnimCategory } from './animData'

// Middle: Animation List (bigger)
export default function AnimationListPanel({ animations }) {
  const {
    animList,
    selectedAnim,
    animFilter,
    setAnimFilter,
    selectedCategory,
    handleLoadAnim
  } = animations

  return (
    <div className="pm-anim-section">
      <div className="pm-anim-header">
        <span>Animations</span>
        <span className="pm-anim-count">
          {animList.filter(a => {
            const matchesCategory = selectedCategory === 'All' || getAnimCategory(a) === selectedCategory
            const matchesFilter = a.toLowerCase().includes(animFilter.toLowerCase()) ||
                                  getAnimDisplayName(a).toLowerCase().includes(animFilter.toLowerCase())
            return matchesCategory && matchesFilter
          }).length}
        </span>
      </div>
      <input
        type="text"
        className="pm-anim-filter"
        placeholder="Search animations..."
        value={animFilter}
        onChange={(e) => setAnimFilter(e.target.value)}
      />
      <div className="pm-anim-list">
        {animList
          .filter(a => {
            const matchesCategory = selectedCategory === 'All' || getAnimCategory(a) === selectedCategory
            const matchesFilter = a.toLowerCase().includes(animFilter.toLowerCase()) ||
                                  getAnimDisplayName(a).toLowerCase().includes(animFilter.toLowerCase())
            return matchesCategory && matchesFilter
          })
          .map(anim => (
            <button
              key={anim}
              className={`pm-anim-item ${selectedAnim === anim ? 'active' : ''}`}
              onClick={() => handleLoadAnim(anim)}
              title={anim}
            >
              {getAnimDisplayName(anim)}
            </button>
          ))}
      </div>
    </div>
  )
}
