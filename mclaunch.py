#!/usr/bin/python3
# MCLaunch

import uuid
from utils import *; logstart('MCLaunch')

class Config:
	mcdir = os.path.abspath('mclaunch/')
	version_manifest = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
	download_chunk_size = 2048
	platform = sys.platform.replace('darwin', 'osx')

@singleton
class VersionManifest:
	def __getitem__(self, x):
		return S(self.json[x])

	@cachedproperty
	def json(self):
		return requests.get(Config.version_manifest).json()

@dispatch
def download(pp, url, fp, size=None):
	r = requests.get(url, stream=True)
	assert r.ok
	if (size is None): size = int(r.raw.getheader('Content-Length', 0)) or inf
	assert (int(r.raw.getheader('Content-Length', 0)) or size) == size

	with open(fp, 'wb') as f:
		for c in pp.iter(r.iter_content(Config.download_chunk_size), size, Config.download_chunk_size):
			f.write(c)

def install(cargs):
	ver = requests.get((VersionManifest['versions']@{'id': cargs.version})[0]['url'])
	ver_json = ver.json()
	fp = os.path.join(Config.mcdir, 'versions', ver_json['id'], ver_json['id']+'.json')
	os.makedirs(os.path.dirname(fp), exist_ok=True)
	open(fp, 'wb').write(ver.content)
	ver = ver_json

	log(f"Downloading Minecraft version {ver['id']}")

	with ThreadedProgressPool() as pp:
		log("Assets")

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

		for i in pp.iter(ver['libraries']):
			if ('rules' in i):
				allow = True
				for r in i['rules']:
					if ('os' in r):
						if (r['os']['name'] != Config.platform): continue
						if ('version' in r['os'] and not re.match(r['os']['version'], platform.release())): continue
					allow = (r['action'] == 'allow')
				if (not allow): continue

			if ('natives' in i):
				assert 'classifiers' in i['downloads'] and 'artifact' not in i['downloads']
				try: i = i['downloads']['classifiers'][i['natives'][Config.platform].replace('${arch}', platform.architecture()[0][:2])]
				except KeyError: continue
			else: i = i['downloads']['artifact']

			fp = os.path.join(Config.mcdir, 'libraries', *i['path'].split('/'))
			os.makedirs(os.path.dirname(fp), exist_ok=True)

			if (os.path.isfile(fp) and (os.stat(fp).st_size != i['size'] or hashlib.sha1(open(fp, 'rb').read()).hexdigest() != i['sha1'])): os.remove(fp)
			if (not os.path.isfile(fp)): download(pp, i['url'], fp, i['size'])

		log("Client")

		client = ver['downloads']['client']

		fp = os.path.join(Config.mcdir, 'versions', ver['id'], ver['id']+'.jar')
		os.makedirs(os.path.dirname(fp), exist_ok=True)
		if (os.path.isfile(fp) and (os.stat(fp).st_size != client['size'] or hashlib.sha1(open(fp, 'rb').read()).hexdigest() != client['sha1'])): os.remove(fp)
		if (not os.path.isfile(fp)): download(pp, client['url'], fp, client['size'])

	log("Installed.")

def list_(cargs):
	types = {'release'}
	if (cargs.snapshot): types.add('snapshot')
	if (cargs.oldalpha): types.add('old_alpha')
	if (cargs.oldbeta): types.add('old_beta')

	r = VersionManifest['versions']@{'type': types}@['id']
	mw = max(map(len, r))+1
	r = r.group(math.ceil(len(r) / (os.get_terminal_size()[0] // (mw+1))))
	print(*(' '.join(r[j][i].ljust(mw) for j in range(len(r)) if i < len(r[j])) for i in range(len(r[0]))), sep='\n')

def run(cargs):
	ver = json.load(open(os.path.join(Config.mcdir, 'versions', cargs.version, cargs.version+'.json')))
	#pprint(ver)

	log(f"Starting Minecraft version {ver['id']}")

	uuid_ = uuid.uuid3(uuid.NAMESPACE_OID, cargs.username).hex
	args = re.sub(r'\$({.*?})', r'\1', ver['minecraftArguments']).format_map({
		'auth_player_name': cargs.username,
		'auth_session': f"token:{uuid_}:{uuid_}",
		'auth_uuid': uuid_,
		'auth_access_token': uuid_,
		'game_directory': Config.mcdir,
		'game_assets': os.path.join(Config.mcdir, 'assets', 'virtual', 'legacy'),
		'assets_root': os.path.join(Config.mcdir, 'assets'),
		'assets_index_name': ver['assetIndex']['id'],
		'user_type': 'legacy',
		'user_properties': '{}',
		'version_name': ver['id'],
	})

	libs = list()
	natives_dir = os.path.join(Config.mcdir, 'natives')

	log("Exctacting natives...")

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

			if ('natives' in i):
				assert 'classifiers' in i['downloads'] and 'artifact' not in i['downloads']
				try: path = i['downloads']['classifiers'][i['natives'][Config.platform].replace('${arch}', platform.architecture()[0][:2])]['path']
				except KeyError: continue
			else: path = i['downloads']['artifact']['path']

			fp = os.path.join(Config.mcdir, 'libraries', *path.split('/'))

			if ('extract' in i):
				with zipfile.ZipFile(fp, 'r') as zf:
					zf.extractall(natives_dir, members=set(zf.namelist())-set(i['extract']['exclude']))
			else: libs.append(fp)

		# TODO: java path
		launch_exec = f"java -Djava.library.path='{natives_dir}' -cp '{os.path.pathsep.join(libs)}:{os.path.join(Config.mcdir, 'versions', ver['id'], ver['id']+'.jar')}' {ver['mainClass']} {args}"

		log("Launching.")
		sys.stderr.write('\n')

		#log(launch_exec, raw=True)

		os.system(launch_exec)
	finally:
		assert os.path.commonpath((Config.mcdir, natives_dir)) == Config.mcdir
		shutil.rmtree(natives_dir)

def main(cargs):
	try: return cargs.func(cargs)
	#except Exception as ex: exception(ex)
	except KeyboardInterrupt as ex: exit(ex)

if (__name__ == '__main__'):
	subparser = argparser.add_subparsers(metavar='<action>')

	args_install = subparser.add_parser('install', help="Install given Minecraft version.")
	args_install.add_argument('version', metavar='<version>')
	args_install.set_defaults(func=install)

	args_list = subparser.add_parser('list', help="List available versions.")
	args_list.add_argument('--snapshot', action='store_true')
	args_list.add_argument('--oldalpha', action='store_true')
	args_list.add_argument('--oldbeta', action='store_true')
	args_list.set_defaults(func=list_)

	args_run = subparser.add_parser('run', help="Run client of given Minecraft version.")
	args_run.add_argument('version', metavar='<version>')
	args_run.add_argument('username', nargs='?', default='Player')
	args_run.set_defaults(func=run)

	argparser.set_defaults(func=lambda *_: sys.exit(argparser.print_help()))
	cargs = argparser.parse_args()
	logstarted(); exit(main(cargs))
else: logimported()

# by Sdore, 2019
