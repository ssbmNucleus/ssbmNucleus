import { ANIM_CATEGORIES } from './animData'

// Category buttons below viewer
export default function CategoryBar({ animations }) {
  const { selectedCategory, setSelectedCategory } = animations

  return (
    <div className="pm-category-bar">
      <button
        className={`pm-cat-btn ${selectedCategory === 'All' ? 'active' : ''}`}
        onClick={() => setSelectedCategory('All')}
      >
        All
      </button>
      {Object.keys(ANIM_CATEGORIES).map(cat => (
        <button
          key={cat}
          className={`pm-cat-btn ${selectedCategory === cat ? 'active' : ''}`}
          onClick={() => setSelectedCategory(cat)}
        >
          {cat}
        </button>
      ))}
    </div>
  )
}
