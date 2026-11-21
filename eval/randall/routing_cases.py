"""Synthetic next-action cases. No actual user records or executable actions."""
GROUPS = {
    'website': ['search_website_mods', 'inspect_website_mod', 'download_website_mod', 'download_website_mods', 'set_website_mod_like'],
    'vault': ['search_vault', 'inspect_mod', 'present_vault_skins', 'preview_portrait', 'organize_skins'],
    'project': ['list_projects', 'inspect_project', 'create_project', 'install_project_mods'],
    'files': ['open_vault_file', 'open_vanilla_file', 'inspect_mod_file', 'unpack_mod_file', 'hsdraw_capabilities', 'hsdraw', 'save_mod_copy'],
    'games': ['player_summary', 'find_games', 'review_game', 'query_game_interactions', 'find_moments', 'queue_clips'],
    'stats': ['player_summary', 'corpus_stats', 'corpus_matchups', 'corpus_trend', 'metric_trend', 'my_deep_stats', 'tier_baseline', 'compare_to_baseline'],
    'coaching': ['player_summary', 'death_breakdown', 'defense_stats', 'stage_stats', 'punish_structure', 'how_i_get_opened', 'kill_efficiency', 'combo_dropoff', 'scout_opponent', 'session_report', 'leak_scan'],
}

CASES = []


def case(identifier, group, prompt, tool=None, args=None, context=None, alternatives=None):
    CASES.append(dict(id=identifier, domain='coach' if group in {'games', 'stats', 'coaching'} else 'mod',
                      group=group, prompt=prompt, context=context or {},
                      expected=([{'name': tool, 'arguments': args or {}}] if tool else []),
                      alternatives=alternatives or []))


# Expected arguments specify semantic intent; runner normalizes documented defaults.
case('m01', 'website', 'Find the six most downloaded Fox character costumes on the website.', 'search_website_mods',
     dict(character='Fox', category='Character Costume', sort_by='download_count', sort_order='desc', limit=6))
case('m02', 'website', 'Find the newest Marth character costumes on the website, six results.', 'search_website_mods',
     dict(character='Marth', category='Character Costume', sort_by='created_at', sort_order='desc', limit=6))
case('m03', 'website', 'Search website Stage Skins tagged night, exclude anime, order by most liked, show six.', 'search_website_mods',
     dict(category='Stage Skin', tags=['night'], exclude_tags=['anime'], sort_by='like_count', sort_order='desc', limit=6))
case('m04', 'website', 'Show the next page with exactly the same website filters.', 'search_website_mods',
     dict(character='Fox', category='Character Costume', sort_by='download_count', sort_order='desc', limit=6, offset=6),
     context={'last_search': dict(character='Fox', category='Character Costume', sort_by='download_count', sort_order='desc', limit=6), 'next_offset': 6})
case('m05', 'website', 'Show the files and description for that website mod.', 'inspect_website_mod', {'post_id': 4102},
     context={'selected_post': {'post_id': 4102, 'title': 'Synthetic Blue Fox'}})
case('m06', 'website', 'Like this website mod.', 'set_website_mod_like', {'post_id': 4102, 'liked': True},
     context={'signed_in': True, 'selected_post': {'post_id': 4102}})
case('m07', 'website', 'Unlike this website mod.', 'set_website_mod_like', {'post_id': 4102, 'liked': False},
     context={'signed_in': True, 'selected_post': {'post_id': 4102}})
case('m08', 'website', 'Download both shown mods, using the default variant of each. Show the combined approval.', 'download_website_mods',
     {'items': [{'post_id': 4102}, {'post_id': 4103}]}, context={'shown_posts': [4102, 4103]})
case('m09', 'website', 'Download it.', context={'shown_posts': [{'post_id': 4102}, {'post_id': 4103}], 'selected_post': None})
case('m10', 'website', 'I like the look of this, but do not like or download it yet.', context={'selected_post': {'post_id': 4102}})
case('m11', 'vault', 'Find my local Marth costumes.', 'search_vault', {'character': 'Marth'})
case('m12', 'vault', 'Find local Fox costumes named Cyber.', 'search_vault', {'character': 'Fox', 'query': 'Cyber'})
case('m13', 'vault', 'Show the two costumes we just found, using their existing artwork.', 'present_vault_skins',
     {'items': [{'character': 'Fox', 'skin_id': 'synthetic-cyber'}, {'character': 'Fox', 'skin_id': 'synthetic-retro'}]},
     context={'last_search_results': [{'character': 'Fox', 'id': 'synthetic-cyber'}, {'character': 'Fox', 'id': 'synthetic-retro'}]})
case('m14', 'vault', 'Render a new CSP for the selected costume.', 'preview_portrait', {'character': 'Fox', 'skin_id': 'synthetic-cyber'},
     context={'selected_skin': {'character': 'Fox', 'skin_id': 'synthetic-cyber'}})
case('m15', 'vault', 'Move these selected costumes into a folder named Favorites. Show me the approval.', 'organize_skins',
     {'character': 'Fox', 'skin_ids': ['synthetic-cyber', 'synthetic-retro'], 'folder_name': 'Favorites'},
     context={'selected_skins': [{'character': 'Fox', 'skin_id': 'synthetic-cyber'}, {'character': 'Fox', 'skin_id': 'synthetic-retro'}]})
case('m16', 'vault', 'Move it into Favorites.', context={'selected_skin': None, 'recent_skins': [{'character': 'Fox', 'skin_id': 'synthetic-cyber'}, {'character': 'Marth', 'skin_id': 'synthetic-blue'}]})
case('m17', 'project', 'List my projects.', 'list_projects')
case('m18', 'project', 'Inspect the Mario costume slots in the selected project.', 'inspect_project', {'project_id': 'synthetic-build', 'character': 'Mario'},
     context={'selected_project_id': 'synthetic-build'})
case('m19', 'project', 'Create a project named Test Night and show its approval.', 'create_project', {'name': 'Test Night'}, context={'vanilla_iso_available': True})
case('m20', 'project', 'Install this inspected Fox costume into the inspected project as an additional slot. Show the approval.', 'install_project_mods',
     {'project_id': 'synthetic-build', 'items': [{'character': 'Fox', 'skin_id': 'synthetic-cyber'}]},
     context={'inspected_project': {'project_id': 'synthetic-build', 'character': 'Fox'}, 'inspected_vault_skin': {'character': 'Fox', 'skin_id': 'synthetic-cyber'}})
case('m21', 'files', 'List the extracted vanilla Mario costume colors.', 'open_vanilla_file', {'character': 'Mario'})
case('m22', 'files', 'Open the vanilla Fox default costume, color Nr.', 'open_vanilla_file', {'character': 'Fox', 'color': 'Nr'})
case('m23', 'files', 'List the members of the attached ZIP.', 'inspect_mod_file', {'file_id': 'a'*32}, context={'attachment': {'file_id': 'a'*32, 'name': 'sample.zip'}})
case('m24', 'files', 'Open exactly costumes/PlFxNr.dat from the inspected ZIP.', 'unpack_mod_file', {'file_id': 'a'*32, 'member': 'costumes/PlFxNr.dat'},
     context={'inspected_zip': {'file_id': 'a'*32, 'members': ['costumes/PlFxNr.dat', 'readme.txt']}})
case('m25', 'files', 'Save it to my vault.', context={'exported_files': [{'file_id': 'a'*32, 'name': 'Fox draft A.dat'}, {'file_id': 'b'*32, 'name': 'Fox draft B.dat'}], 'selected_file': None})

case('c01', 'games', 'Find my last loss against Marth.', 'find_games', {'matchup': 'Marth', 'result': 'loss', 'limit': 1})
case('c02', 'games', 'Find my last three wins playing Fox against Falco.', 'find_games', {'character': 'Fox', 'matchup': 'Falco', 'result': 'win', 'limit': 3})
case('c03', 'games', 'Find my five most recent deaths to Fox back air.', 'find_moments', {'role': 'against_me', 'vs_character': 'Fox', 'ender': 'bair', 'killed': True, 'sort': 'recent', 'limit': 5})
case('c04', 'games', 'Find my three best Falco combos.', 'find_moments', {'role': 'mine', 'character': 'Falco', 'sort': 'best', 'limit': 3})
case('c05', 'games', 'Find my four latest Falco conversions starting with down air against Marth.', 'find_moments',
     {'role': 'mine', 'character': 'Falco', 'vs_character': 'Marth', 'opener': 'dair', 'sort': 'recent', 'limit': 4})
case('c06', 'games', 'Review the game we just located.', 'review_game', {'game_id': 7001}, context={'located_game': {'game_id': 7001}})
case('c07', 'games', 'Show the entire game we just located.', 'queue_clips', {'moments': [{'game_id': 7001}]}, context={'located_game': {'game_id': 7001}})
case('c08', 'games', 'Show both clips just returned, in the same order.', 'queue_clips', {'moments': [{'ref': 'synthetic-ref-A'}, {'ref': 'synthetic-ref-B'}]},
     context={'find_moments_results': [{'ref': 'synthetic-ref-A', 'label': 'dair to bair'}, {'ref': 'synthetic-ref-B', 'label': 'shine to bair'}]})
case('c09', 'games', 'Show it.', context={'located_games': [7001, 7002], 'selected_game': None, 'moments': []})
case('c10', 'games', 'Find eight examples of the conversions my opponent did to me in that game.', 'query_game_interactions',
     {'game_id': 7001, 'perspective': 'received', 'limit': 8}, context={'selected_game_id': 7001})
case('c11', 'stats', 'What is my Marth win/loss record against Fox? Use the full corpus.', 'corpus_matchups', {'as_character': 'Marth', 'vs_character': 'Fox'})
case('c12', 'stats', 'Fetch my monthly Falco-versus-Fox win-rate trend.', 'corpus_trend', {'as_character': 'Falco', 'vs_character': 'Fox', 'bucket': 'month'})
case('c13', 'stats', 'Fetch my quarterly Fox tech-rate trend.', 'metric_trend', {'character': 'Fox', 'metric': 'tech_rate', 'bucket': 'quarter'})
case('c14', 'stats', 'Fetch my monthly Falco L-cancel trend against Marth.', 'metric_trend', {'character': 'Falco', 'metric': 'lc_rate', 'vs_character': 'Marth', 'bucket': 'month'})
case('c15', 'stats', 'Fetch deep stats for my most recent 50 Marth games.', 'my_deep_stats', {'character': 'Marth', 'last_n': 50})
case('c16', 'stats', 'Fetch my Fox deep stats for January 2025 only.', 'my_deep_stats', {'character': 'Fox', 'since': '2025-01', 'until': '2025-01'})
case('c17', 'stats', 'Fetch the diamond Fox baseline pack.', 'tier_baseline', {'character': 'Fox', 'tier': 'diamond'})
case('c18', 'stats', 'Show my full-corpus stage records when I play Marth.', 'corpus_stats', {'section': 'stages', 'as_character': 'Marth'})
case('c19', 'stats', 'Compare my Falco L-cancel rate with the diamond baseline.', 'compare_to_baseline', {'metric': 'lc_rate', 'tier': 'diamond', 'character': 'Falco'})
case('c20', 'stats', 'Compare that period with the other one.', context={'date_windows': [], 'prior_subject': None})
case('c21', 'coaching', 'Fetch my session report for September 12, 2026.', 'session_report', {'date': '2026-09-12'})
case('c22', 'coaching', 'Scout my opponent TEST#123.', 'scout_opponent', {'opponent': 'TEST#123'})
case('c23', 'coaching', 'Fetch how often my Falco closes kill windows against Marth; use 100 percent as the cutoff.', 'kill_efficiency', {'character': 'Falco', 'vs_character': 'Marth', 'kill_threshold': 100})
case('c24', 'coaching', 'Find where my Falco down-air conversions stall against Fox.', 'combo_dropoff', {'character': 'Falco', 'vs_character': 'Fox', 'opener': 'dair'})
case('c25', 'coaching', 'Scout him.', context={'opponent_candidates': ['TEST#123', 'DEMO#456'], 'selected_opponent': None})

assert len(CASES) == 50
