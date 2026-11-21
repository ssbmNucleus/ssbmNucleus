# Melee Files Reference

This is a cleaned Markdown conversion of the useful reference material from the original "Melee Files" PDF.

Source: [original Google Doc](https://docs.google.com/document/d/1Q9uY3b9Xd-aUGHVsCLvLc6zR11-5DCPSHBSXb6mAjA8/edit?tab=t.0)

## System Files

- `main.dol` / `<Start.dol>`: main executable; most game code and logic
- `boot.bin` / `<ISO.hdr>`: `GALE01`, game name, and description
- `bi2.bin` / `<ISO.hdr>`: secondary boot data
- `apploader.img` / `<AppLoader.img>`: Nintendo apploader
- `fst.bin` / `<Game.toc>`: file system table for `/files`, including offsets and sizes

## Useful General Notes

- `.usd` is basically `.dat` with extra localization data
- changing file sizes means `fst.bin` has to reflect the new offsets and sizes
- most GameCube ISO rebuilders handle `fst.bin` and `boot.bin` updates automatically

## Root File Families

- `Ty*.dat`: trophy and assorted item-related files
- `Mn*.dat`: menu files
- `Mv*.mth`: movie files
- `Pl*.dat`: player or character files
- `Pl*AJ.dat`: character animation joint files
- `Gr*.dat`: stage files
- `GrT*.dat`: target-test stages
- `Gm*.dat`, `Gm*.thp`: game or scene data, including videos
- `GmRstM*.dat`: demo result motion
- `Ef*.dat`: effect data
- `If*.dat`: interface-related files
- `Ir*.dat`: library data
- `Lb*.dat`: library-related files
- `Nt*.dat`: text data
- `Sd*.dat`: visual or demo-related files
- `Vi*.dat`: projectile and Kirby-related files
- `opening.bnr`: banner image and metadata shown by the console or emulator menu
- `usa.ini`: empty file in this reference
- `DbCo.dat`: debug common data
- `ItCo.dat`: item common data
- `PdPm.dat`: player manager-related data
- `SmSt.dat`: sound-manager-related data
- `TmBox.dat`: tournament box data

## Menu File Notes

Some menu prefixes called out in the source:

- `MnExtAll`: general menu data
- `MnMaAll`: main menu
- `MnNamedef`: name creation
- `MnSlChr`: character select screen
- `MnSlMap`: stage select screen

## Player Prefixes

These are the main two-letter character codes used in `Pl*.dat` naming:

- `Bo`: male wireframe
- `Ca`: Captain Falcon
- `Ch`: Crazy Hand
- `Cl`: Young Link
- `Co`: common
- `Dk`: Donkey Kong
- `Dr`: Dr. Mario
- `Fc`: Falco
- `Fe`: Roy
- `Fx`: Fox
- `Gk`: Giga Bowser
- `Gl`: female wireframe
- `Gn`: Ganondorf
- `Gw`: Mr. Game & Watch
- `Kb`: Kirby
- `Kp`: Bowser
- `Lg`: Luigi
- `Lk`: Link
- `Mh`: Master Hand
- `Mr`: Mario
- `Ms`: Marth
- `Mt`: Mewtwo
- `Nn`: Nana
- `Ns`: Ness
- `Pc`: Pichu
- `Pe`: Peach
- `Pk`: Pikachu
- `Pp`: Popo
- `Pr`: Jigglypuff
- `Sb`: Sandbag
- `Sk`: Sheik
- `Ss`: Samus
- `Ys`: Yoshi
- `Zd`: Zelda

## Costume Color Suffixes

These are the color codes used in costume-specific player files:

- `Aq`: Aqua
- `Bk`: Black
- `Bu`: Blue
- `Gr`: Green
- `Gy`: Gray
- `La`: Lavender
- `Nr`: Neutral
- `Or`: Orange
- `Pi`: Pink
- `Re`: Red
- `Wh`: White
- `Ye`: Yellow

So a costume archive usually looks like `PlXxYy.dat`.

## Stage Codes

The source also lists the common `Gr*.dat` stage codes:

- `GrBB`: Big Blue
- `GrCn`: Corneria
- `GrCs`: Princess Peach's Castle
- `GrEF1`: Goomba Trophy Stage
- `GrEF2`: Entei Trophy Stage
- `GrEF3`: Majora's Mask Trophy Stage
- `GrFs`: Fourside
- `GrFz`: Flat Zone
- `GrGb`: Great Bay
- `GrGd`: Kongo Jungle
- `GrGr`: Green Greens
- `GrHe`: Heal / All-Star
- `GrHr`: Home-Run Contest
- `GrI1`: Mushroom Kingdom
- `GrI2`: Mushroom Kingdom II
- `GrIm`: Icicle Mountain
- `GrIz`: Fountain of Dreams
- `GrKg`: Jungle Japes
- `GrKr`: Brinstar Depths
- `GrMc`: Mute City
- `GrNBa`: Battlefield
- `GrNBr`: F-Zero adventure-mode stage
- `GrNFg`: Figure Get trophy stage
- `GrNKr`: Mushroom Kingdom adventure-mode stage
- `GrNLa`: Final Destination
- `GrNPo`: Pushon?
- `GrNSr`: Hyrule adventure-mode route
- `GrNZr`: Brinstar adventure-mode route
- `GrOk`: Kongo Jungle 64
- `GrOp`: Dream Land 64
- `GrOt`: Onett
- `GrOy`: Yoshi's Story 64
- `GrPs`: Pokemon Stadium
- `GrPs1`: Pokemon Stadium Fire
- `GrPs2`: Pokemon Stadium Grass
- `GrPs3`: Pokemon Stadium Water
- `GrPs4`: Pokemon Stadium Rock
- `GrPu`: Poke Floats
- `GrRc`: Rainbow Cruise
- `GrSh`: Hyrule Temple
- `GrSt`: Yoshi's Story
- `GrTe`: Test stage
- `GrVe`: Venom
- `GrYt`: Yoshi's Island
- `GrZe`: Brinstar

## A Few Concrete Ownership Notes From The Source

- `Ef*.dat` is the effect-data family
- `EfCoData.dat` is called out as common effects such as smoke and dust
- `PlCo.dat` is the common player-data file
- `MnSlChr` holds random-stage-select stage names
- `GmPause` is the pause interface

## Useful Rule Of Thumb

- If it is a skin, start with `PlXxYy.dat`.
- If it affects one character across multiple skins or moves, check `PlXx.dat`.
- If it affects multiple characters or shared particles, check `Ef*.dat`.
- If it is a stage, look at `Gr*.dat` or `.usd`.

## Audio Files

### `files/audio`

- `1p_qk.hps`: Healing Room Theme (All-Star Mode)
- `akaneia.hps`: Fire Emblem Theme (alt theme on Temple)
- `balloon.hps`: Fighter Theme (alt theme on Icicle Mountain)
- `bigblue.hps`: Big Blue
- `castle.hps`: Peach's Castle Theme
- `continue.hps`: Continue? clip
- `corneria.hps`: Corneria
- `docmari.hps`: Dr. Mario's theme
- `ending.hps`: plays in the short cutscene after you complete a 1-Player mode
- `famidemo.hps`: unknown, possibly related to the 15-minute special movie
- `ff_1p01.hps`: Classic Mode Stage Complete
- `ff_1p02.hps`: Classic Mode Stage Complete
- `ff_bad.hps`: unused "success" theme
- `ff_good.hps`: unused "success" theme
- `ff_<dood>.dhps`: character fanfares
- `ff_step{1,2,3}.hps`: unused fanfares
- `flatzone.hps`: Flat Zone
- `fourside.hps`: Fourside
- `gameover.hps`: Game Over jingle
- `garden.hps`: Kongo Jungle Melee
- `greatbay.hps`: Great Bay
- `greens.hps`: Green Greens
- `howto.hps` and `howto_s.hps`: How to Play themes; one plays on the title screen after idling and one plays when How to Play is selected in the data files
- `hyaku.hps`: Multi-Man Melee 1 theme, also alt on Battlefield
- `hyaku2.hps`: Multi-Man Melee 2 theme, also alt on Final Destination
- `icemt.hps`: Ice Mountain
- `inis1_01.hps`: Mushroom Kingdom I
- `inis2_01.hps`: Mushroom Kingdom II
- `inis1_02.hps` and `inis2_02.hps`: tracks that play on Kingdom I and II when there are 30 seconds left or a player is on their last stock
- `intro_es.hps`: Classic Mode Intro jingle
- `intro_nm.hps`: Adventure Mode Intro jingle
- `item_h.hps`: Hammer music, only used in Sound Test
- `item_s.hps`: Starman music, only used in Sound Test
- `izumi.hps`: Fountain of Dreams
- `kongo.hps`: Jungle Japes
- `kraid.hps`: Brinstar Depths
- `menu01.hps` and `menu3.hps`: menu music, with `menu01` as the main one
- `menu02.hps`: Trophy Collector or trophy-viewing theme; the source also notes it may be an alternate menu theme that plays randomly
- `mrider.hps`: Mach Rider theme, alt on Big Blue
- `mutecity.hps`: Mute City
- `old_dk.hps`: Kongo Jungle 64
- `old_kb.hps`: Dream Land 64
- `old_ys.hps`: Yoshi's Island 64
- `onetto.hps`: Onett
- `onetto2.hps`: Mother 2 Theme, alt on Onett
- `opening.hps`: audio that goes with `MvOpen.mth`, the game's intro sequence
- `pokesta.hps`: Battle Theme, alt on Pokemon Stadium
- `pstadium.hps`: Pokemon Stadium
- `pura.hps`: Poke Floats
- `rcruise.hps`: Rainbow Cruise
- `s_info{1,2,3}.hps` and `s_new{1,2}.hps`: achievement jingles; which one plays depends on the type of achievement
- `s_newcom.hps`: Challenger Approaching jingle
- `s_select.hps`: unused; a copy of `item_h.hps`
- `saria.hps`: Saria's Theme, alt on Great Bay
- `shrine.hps`: Temple
- `siren.hps`: "Warning Siren", plays on the second stage of Brinstar in Adventure Mode
- `smari3.hps`: Super Mario Bros. 3, alt on Yoshi's Island Melee
- `sp_end.hps`: Final Destination
- `sp_giga.hps`: Giga Bowser theme, used in Adventure Mode Final Destination and Event 51
- `sp_metal.hps`: Metal Theme, used in Adventure Mode Battlefield and Classic stage 11
- `sp_zako.hps`: Battlefield
- `swm_15min.hps`: audio attributed to `MvOmake15.mth`, the Special Movie
- `target.hps`: Break the Targets theme
- `venom.hps`: Venom
- `vl_*.hps`: Adventure Mode audio, mainly for cutscenes
- `vs_hyou1.hps` and `vs_hyou2.hps`: Tournament Mode themes
- `yorster.hps`: Yoshi's Island Melee
- `ystory.hps`: Yoshi's Story
- `zebes.hps`: Brinstar

### `files/audio/us`

- lots of localization audio files
- `nr_name.ssm`: announcer voicing character names on the character select screen

## Original File

The original PDF is not kept in the repo.
