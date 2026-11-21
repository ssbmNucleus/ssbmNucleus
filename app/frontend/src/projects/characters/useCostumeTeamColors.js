import { useState } from 'react'
import { playSound } from '../../shared/audio/sounds'
import { api } from '../../shared/transport/api'

export const EMPTY_TEAM = { red: null, blue: null, green: null }

// Team colors for the costumes panel: which installed costume each team color
// (red/blue/green) uses, picking a color, and assigning it to a costume, for
// one fighter or either row of the Zelda/Sheik pair.
export function useCostumeTeamColors({ selectedFighter, pairTeamColors, fetchPair }) {
  // Team color state
  const [teamColors, setTeamColors] = useState({ red: null, blue: null, green: null })
  const [selectedTeamColor, setSelectedTeamColor] = useState(null)

  const fetchTeamColors = async (fighterName) => {
    try {
      const data = await api.get(`/fighters/${encodeURIComponent(fighterName)}/team-colors`)
      setTeamColors({
        red: data.red,
        blue: data.blue,
        green: data.green
      })
    } catch (err) {
      console.error('Failed to fetch team colors:', err)
      setTeamColors({ red: null, blue: null, green: null })
    }
  }

  const handleTeamColorClick = (color) => {
    playSound('boop')
    setSelectedTeamColor(selectedTeamColor === color ? null : color)
  }

  const handleCostumeTeamAssign = async (costumeIndex) => {
    if (!selectedTeamColor || !selectedFighter) return

    try {
      await api.post(`/fighters/${encodeURIComponent(selectedFighter.name)}/team-colors`, {
        color: selectedTeamColor,
        costumeIndex: costumeIndex
      })

      playSound('newSkin')
      await fetchTeamColors(selectedFighter.name)
      setSelectedTeamColor(null)
    } catch (err) {
      console.error('Failed to set team color:', err)
    }
  }

  // Get the team color assigned to a costume index
  const getCostumeTeamColor = (costumeIndex) => {
    const colors = []
    if (teamColors.red === costumeIndex) colors.push('red')
    if (teamColors.blue === costumeIndex) colors.push('blue')
    if (teamColors.green === costumeIndex) colors.push('green')
    return colors
  }

  // Pair-view variants: team colors are PER FIGHTER, so the combined view
  // assigns/reads against whichever row (Zelda or Sheik) the tile lives in.
  const getPairCostumeTeamColor = (fighterName, costumeIndex) => {
    const tc = pairTeamColors[fighterName] || EMPTY_TEAM
    const colors = []
    if (tc.red === costumeIndex) colors.push('red')
    if (tc.blue === costumeIndex) colors.push('blue')
    if (tc.green === costumeIndex) colors.push('green')
    return colors
  }

  const handlePairCostumeTeamAssign = async (fighterName, costumeIndex) => {
    if (!selectedTeamColor) return
    try {
      await api.post(`/fighters/${encodeURIComponent(fighterName)}/team-colors`, {
        color: selectedTeamColor,
        costumeIndex
      })
      playSound('newSkin')
      await fetchPair()
      setSelectedTeamColor(null)
    } catch (err) {
      console.error('Failed to set team color:', err)
    }
  }

  return {
    teamColors, selectedTeamColor, setSelectedTeamColor, fetchTeamColors, handleTeamColorClick,
    handleCostumeTeamAssign, getCostumeTeamColor, getPairCostumeTeamColor, handlePairCostumeTeamAssign,
  }
}
