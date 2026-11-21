// Keep each climber's DAT and painted textures separate across viewer reloads.
export function createPaintPair(members) {
  if (!Array.isArray(members) || members.length !== 2 ||
      members[0].name !== 'Popo' || members[1].name !== 'Nana' ||
      members.some(member => !member.datName || !member.datBase64 || !member.datFile)) {
    throw new Error('The Ice Climbers costume is missing a complete Popo/Nana pair.')
  }
  return members.map(member => ({ ...member, memberId: member.name.toLowerCase(), edits: {} }))
}

export function addPaintPairToZip(zip, members) {
  for (const member of members) zip.file(member.datName, member.datBase64, { base64: true })
}
