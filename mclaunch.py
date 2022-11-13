#!/usr/bin/python3
# MCLaunch

import uuid, requests
from utils.nolog import *

@export
class Config:
	mcdir = os.path.expanduser('~/.minecraft/')
	version_manifest = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
	tl_versions = "https://u.tlauncher.ru/repo/versions/versions.json" # TODO
	download_chunk_size = 2048
	platform = sys.platform.replace('darwin', 'osx')

@export
@singleton
class VersionManifest:
	def __getitem__(self, x):
		return S(self.json[x])

	@cachedproperty
	def json(self):
		return requests.get(Config.version_manifest).json()

@export
@dispatch
def download(pp, url, fp, size=None):
	r = requests.get(url, stream=True)
	assert r.ok
	if (size is None): size = int(r.raw.getheader('Content-Length', 0)) or inf
	assert (int(r.raw.getheader('Content-Length', 0)) or size) == size

	with open(fp, 'wb') as f:
		for c in pp.iter(r.iter_content(Config.download_chunk_size), size, Config.download_chunk_size, add_base=(1024, ('B', 'KiB', 'MiB', 'GiB', 'TiB'))):
			f.write(c)

@apcmd(metavar='<action>')
@aparg('version', metavar='<version>')
@aparg('--skip-assets', action='store_true')
@aparg('--skip-libraries', action='store_true')
def install(cargs):
	""" Install given Minecraft version. """

	if (cargs.version == 'latest'): cargs.version = VersionManifest['latest']['release']
	elif (cargs.version == 'latest-snapshot'): cargs.version = VersionManifest['latest']['snapshot']

	ver = requests.get((VersionManifest['versions']@{'id': cargs.version})[0]['url'])
	ver_json = ver.json()
	fp = os.path.join(Config.mcdir, 'versions', ver_json['id'], ver_json['id']+'.json')
	os.makedirs(os.path.dirname(fp), exist_ok=True)
	open(fp, 'wb').write(ver.content)
	ver = ver_json

	log(f"Downloading Minecraft version {ver['id']}")

	with ThreadedProgressPool(fixed=True, add_base=True, add_speed_eta=True) as pp:
		log("Assets")

		if (cargs.skip_assets): log('(skipped)')
		else:
			assets = requests.get(ver['assetIndex']['url'])
			assert (hashlib.sha1(assets.content).hexdigest() == ver['assetIndex']['sha1'])
			fp = os.path.join(Config.mcdir, 'assets', 'indexes', ver['assetIndex']['id']+'.json')
			os.makedirs(os.path.dirname(fp), exist_ok=True)
			open(fp, 'wb').write(assets.content)
			assets = assets.json()

			for k, v in pp.iter(assets['objects'].items()):
				fp = os.path.join(Config.mcdir, 'assets', 'objects', v['hash'][:2], v['hash'])
				os.makedirs(os.path.dirname(fp), exist_ok=True)

				if (os.path.isfile(fp) and os.stat(fp).st_size != v['size']): os.remove(fp)
				if (not os.path.isfile(fp)): download(pp, f"http://resources.download.minecraft.net/{v['hash'][:2]}/{v['hash']}", fp, v['size'])
				lp = os.path.join(Config.mcdir, 'assets', 'virtual', 'legacy', *k.split('/'))
				os.makedirs(os.path.dirname(lp), exist_ok=True)
				if (os.path.isfile(lp) and os.stat(lp).st_size != v['size']): os.remove(lp)
				if (not os.path.isfile(lp)): os.link(fp, lp)

		log("Libraries")

		if (cargs.skip_libraries): log('(skipped)')
		else:
			for i in pp.iter(ver['libraries']):
				if ('rules' in i):
					allow = True
					for r in i['rules']:
						if ('os' in r):
							if (r['os']['name'] != Config.platform): continue
							if ('version' in r['os'] and not re.match(r['os']['version'], platform.release())): continue
						allow = (r['action'] == 'allow')
					if (not allow): continue

				if ('artifact' in i['downloads']):
					a = i['downloads']['artifact']

					fp = os.path.join(Config.mcdir, 'libraries', *a['path'].split('/'))
					os.makedirs(os.path.dirname(fp), exist_ok=True)

					if (os.path.isfile(fp) and (os.stat(fp).st_size != a['size'] or hashlib.sha1(open(fp, 'rb').read()).hexdigest() != a['sha1'])): os.remove(fp)
					if (not os.path.isfile(fp)): download(pp, a['url'], fp, a['size'])

				if ('natives' in i):
					assert 'classifiers' in i['downloads']
					try: a = i['downloads']['classifiers'][i['natives'][Config.platform].replace('${arch}', platform.architecture()[0][:2])]
					except KeyError: continue

					fp = os.path.join(Config.mcdir, 'libraries', *a['path'].split('/'))
					os.makedirs(os.path.dirname(fp), exist_ok=True)

					if (os.path.isfile(fp) and (os.stat(fp).st_size != a['size'] or hashlib.sha1(open(fp, 'rb').read()).hexdigest() != a['sha1'])): os.remove(fp)
					if (not os.path.isfile(fp)): download(pp, a['url'], fp, a['size'])

		log("Client")

		client = ver['downloads']['client']

		fp = os.path.join(Config.mcdir, 'versions', ver['id'], ver['id']+'.jar')
		os.makedirs(os.path.dirname(fp), exist_ok=True)
		if (os.path.isfile(fp) and (os.stat(fp).st_size != client['size'] or hashlib.sha1(open(fp, 'rb').read()).hexdigest() != client['sha1'])): os.remove(fp)
		if (not os.path.isfile(fp)): download(pp, client['url'], fp, client['size'])

	log("Installed.")

@apcmd(metavar='<action>')
@aparg('--snapshot', action='store_true')
@aparg('--oldalpha', action='store_true')
@aparg('--oldbeta', action='store_true')
def list_(cargs):
	""" List available versions. """

	types = {'release'}
	if (cargs.snapshot): types.add('snapshot')
	if (cargs.oldalpha): types.add('old_alpha')
	if (cargs.oldbeta): types.add('old_beta')

	r = VersionManifest['versions']@{'type': types}@['id']
	mw = max(map(len, r))+1
	r = r.group(math.ceil(len(r) / (os.get_terminal_size()[0] // (mw+1))))
	print(*(' '.join(r[j][i].ljust(mw) for j in range(len(r)) if i < len(r[j])) for i in range(len(r[0]))), sep='\n')

@apcmd(metavar='<action>')
@aparg('version', metavar='<version>')
@aparg('-name', metavar='<username>', dest='username', default=os.getenv('USER', 'Player'))
@aparg('-class', metavar='<main class>', dest='main_class', nargs='?')
@aparg('--dont-remove-natives', action='store_true')
def run(cargs):
	""" Run client of given Minecraft version. """

	if (cargs.version == 'latest'): cargs.version = VersionManifest['latest']['release']
	elif (cargs.version == 'latest-snapshot'): cargs.version = VersionManifest['latest']['snapshot']

	ver = json.load(open(os.path.join(Config.mcdir, 'versions', cargs.version, cargs.version+'.json')))
	#pprint(ver)

	log(f"Starting Minecraft version {ver['id']}")


	libs = list()
	natives_dir = os.path.join(Config.mcdir, 'natives')
	extract_natives = not os.path.isdir(natives_dir)

	log("Unpacking natives...")

	try:
		for i in ver['libraries']:
			if ('rules' in i):
				allow = True
				for r in i['rules']:
					if ('os' in r):
						if (r['os']['name'] != Config.platform): continue
						if ('version' in r['os'] and not re.match(r['os']['version'], platform.release())): continue
					allow = (r['action'] == 'allow')
				if (not allow): continue

			if ('artifact' in i['downloads']): path = i['downloads']['artifact']['path']
			else: path = None

			if ('natives' in i):
				assert 'classifiers' in i['downloads']
				try: path = i['downloads']['classifiers'][i['natives'][Config.platform].replace('${arch}', platform.architecture()[0][:2])]['path']
				except KeyError: pass

			if (path is None): continue

			fp = os.path.join(Config.mcdir, 'libraries', *path.split('/'))

			if ('extract' in i):
				if (extract_natives):
					with zipfile.ZipFile(fp, 'r') as zf:
						zf.extractall(natives_dir, members=set(zf.namelist())-set(i['extract']['exclude']))
			else: libs.append(fp)

		main_class = cargs.main_class if (cargs.main_class is not None) else ver['mainClass']

		uuid_ = uuid.uuid3(uuid.NAMESPACE_OID, cargs.username).hex
		argmap = {
			'auth_player_name': cargs.username,
			'auth_session': f"token:{uuid_}:{uuid_}",
			'auth_uuid': uuid_,
			'auth_access_token': uuid_,
			'game_directory': Config.mcdir,
			'game_assets': os.path.join(Config.mcdir, 'assets', 'virtual', 'legacy'),
			'assets_root': os.path.join(Config.mcdir, 'assets'),
			'assets_index_name': ver['assetIndex']['id'],
			'classpath': f"{os.path.pathsep.join(libs)}:{os.path.join(Config.mcdir, 'versions', ver['id'], ver['id']+'.jar')}",
			'natives_directory': natives_dir,
			'launcher_name': 'mclaunch',
			'launcher_version': '',
			'user_type': 'legacy',
			'user_properties': '{}',
			'version_name': ver['id'],
			'version_type': ver['type'],
		}

		try: jvm_args = re.sub(r'\$({.*?})', r'\1', ' '.join(i for i in ver['arguments']['jvm'] if isinstance(i, str))).format_map(argmap)
		except KeyError: jvm_args = f"-Djava.library.path='{argmap['natives_directory']}' -cp '{argmap['classpath']}'"
		try: argstring = ' '.join(i for i in ver['arguments']['game'] if isinstance(i, str)) # TODO
		except KeyError: argstring = ver['minecraftArguments'] # TODO FIXME
		game_args = re.sub(r'\$({.*?})', r'\1', argstring).format_map(argmap)

		# TODO: java path
		launch_exec = f"java {jvm_args} {main_class} {game_args}"

		log("Launching.")
		sys.stderr.write('\n')

		log(1, launch_exec, raw=True)

		os.system(launch_exec)
	finally:
		if (extract_natives and not cargs.dont_remove_natives):
			assert os.path.commonpath((Config.mcdir, natives_dir)) == Config.mcdir
			shutil.rmtree(natives_dir)

@apmain
@aparg('--mcdir', metavar='path', help="Minecraft directory", default='~/.minecraft')
def main(cargs):
	Config.mcdir = os.path.expanduser(cargs.mcdir)
	try: return cargs.func(cargs)
	except KeyboardInterrupt as ex: exit(ex)

# by Sdore, 2019-2022
