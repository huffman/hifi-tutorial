#!/usr/bin/env python
# This tool generates a serverless content set from the `src` directory:
#  * Bakes all models
#  * Remaps the following URLs in properties in models.json.gz file from `atp:/` to `file:///~/`:
#    * modelURL
#    * script
#    * textures (JSON value with references to textures)
#    * skybox (?)
#    * serverScripts


from __future__ import print_function
import sys
import os
import json
import subprocess
import collections
import shutil

verbose_logging = False

def log(prefix, *args):
    print(prefix, *args)
    sys.stdout.flush()

def debug(*args):
    if verbose_logging:
        log('[DEBUG]', *args)

def info(*args):
    log('[INFO]', *args)

def error(*args):
    log('[ERROR]', *args)

oven_path = os.environ['HIFI_OVEN']

def makedirs(path):
    """
    Create directory `path`, including its parent directories if they do
    not already exist. Return True if the directory did not exist and was
    created, or False if it already existed.
    """
    try:
        os.makedirs(path)
        return True
    except:
        return False

def get_extension(path):
    """Return the extension after the last '.' in a path. """
    idx = path.rfind('.')
    if idx >= 0:
        return path[idx + 1:]
    return ''

def get_filename(path):
    """Return the filename portion of a path. """
    _head, tail = os.path.split(path)
    return tail

def get_basename(path):
    filename = get_filename(path)
    idx = filename.find('.')
    if idx == -1:
        return filename
    return filename[:idx]

def bake_asset(abs_asset_path, baked_asset_output_dir):
    makedirs(baked_asset_output_dir)
    ext = get_extension(abs_asset_path)
    filetype = ''
    abs_baked_path = ''

    directory, filename = os.path.split(abs_asset_path)
    basename = get_basename(filename)
    baked_output_filename = ''

    if ext == 'fbx':
        filetype = 'fbx'
        baked_output_filename = basename + '.baked.fbx'
    elif ext in ('.png'):
        filetype = 'texture'
        baked_output_filename = basename + '.texmeta.json'
    else:
        return None

    with open(os.devnull, 'w') as devnull:
        process = subprocess.Popen([oven_path,
                                   '-i', abs_asset_path,
                                   '-o', baked_asset_output_dir,
                                   '-t', filetype],
                                   stdout=devnull,
                                   stderr=devnull)
        process.wait()

    return os.path.join(baked_asset_output_dir, baked_output_filename)

Asset = collections.namedtuple('Asset', [
    'filename',       # Original asset filename. Baked assets might have a different output filename
    'rel_dirpath',   # Relative path to asset dir, relative to `src/assets/`, starting with a `/`
    'atp_path',       # Path to asset, as it would appear on the asset server
    'input_abs_path', # Absolute path to file on file system
])

def joinpath(*args):
    return '/'.join((el for el in args if el != ''))

def build_serverless_tutorial_content(input_dir, output_dir):
    info("Building serverless tutorial content")
    info("  Input directory: " + input_dir)
    info("  Output directory: " + output_dir)

    input_assets_dir = os.path.join(input_dir, 'assets')
    input_entities_dir = os.path.join(input_dir, 'entities')
    input_ds_dir = os.path.join(input_dir, 'domain-server')

    input_models_filepath = os.path.join(input_entities_dir, 'models.json')
    output_models_filepath = os.path.join(output_dir, 'models.json')
    
    # Ex: atp:/models/someFile.fbx => file:///~/baked/models/someFile.fbx/someFile.baked.fbx
    # Ex: atp:/script.js => file:///~/original/script.js
    atp_path_to_output_path = {}
    
    # Collect list of all assets and their abs path
    assets = []
    for dirpath, _dirs, files in os.walk(input_assets_dir):
        for filename in files:
            asset_rel_dir = os.path.relpath(dirpath, input_assets_dir).replace('\\', '/')
            if asset_rel_dir == '.':
                asset_rel_dir = ''
            else:
                asset_rel_dir = asset_rel_dir

            abs_asset_path = os.path.normpath(
                    os.path.join(input_assets_dir, dirpath, filename))

            atp_path = '/'.join((el for el in ('atp:', asset_rel_dir, filename) if el != ''))

            assets.append(Asset(filename, asset_rel_dir, atp_path, abs_asset_path))


    # Bake all assets
    for asset in assets:
        if asset.filename.endswith('.fbx'):
            info("Baking", '/' + joinpath(asset.rel_dirpath, asset.filename))
            baked_asset_output_dir = os.path.abspath(os.path.join(output_dir, 'baked', asset.rel_dirpath, asset.filename))
            output_abs_path = bake_asset(asset.input_abs_path, baked_asset_output_dir)
            system_local_path = 'file:///~/serverless/' + os.path.relpath(output_abs_path, output_dir).replace('\\', '/')
            debug("Baked: " + asset.atp_path + " => " + system_local_path)
            atp_path_to_output_path[asset.atp_path] = system_local_path
        else:
            output_abs_dir = os.path.join(output_dir, 'original', asset.rel_dirpath)
            output_abs_path = os.path.join(output_abs_dir, asset.filename)
            info("Copying", '/' + joinpath(asset.rel_dirpath, asset.filename))
            debug("  Copying", asset.input_abs_path, 'to', output_abs_path)
            makedirs(output_abs_dir)
            shutil.copyfile(asset.input_abs_path, output_abs_path)
            system_local_path = joinpath('file:///~/serverless', asset.rel_dirpath, 'original', asset.filename)
            atp_path_to_output_path[asset.atp_path] = system_local_path

    entities = None
    with open(input_models_filepath, 'r') as models_file:
        try:
            entities = json.load(models_file)
        except:
            error("ERROR: Failed to load models file")
            raise

    def cleanup_url(url):
        idx = url.find('?')
        if idx != -1:
            url = url[:idx]
        return url

    def to_system_local_url(url):
        clean_url = cleanup_url(url)
        if clean_url not in atp_path_to_output_path:
            if clean_url.endswith('.fst'):
                info("FST not found in local list of assets, but probably needs to be on a remote server: " + url)
            else:
                error("Not found in local list of assets: " + url)
        else:
            return atp_path_to_output_path[clean_url]
        return url

    # Update URLs 
    debug("Found " + str(len(entities['Entities'])) + " entities")
    for entity in entities['Entities']:
        if 'modelURL' in entity:
            entity['modelURL'] = to_system_local_url(entity['modelURL'])
        if 'script' in entity:
            entity['script'] = to_system_local_url(entity['script'])
        if 'serverScripts' in entity:
            entity['serverScripts'] = to_system_local_url(entity['serverScripts'])
        if 'ambientLight' in entity:
            al = entity['ambientLight']
            for key in al:
                al[key] = to_system_local_url(al[key])
        if 'skybox' in entity:
            skybox = entity['skybox']
            for key in skybox:
                skybox[key] = to_system_local_url(skybox[key])

    with open(output_models_filepath, 'w') as models_file:
        json.dump(entities, models_file, indent=4)

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: " + sys.argv[0] + "input_dir output_dir")
        sys.exit(1)

    input_dir = os.path.abspath(sys.argv[1])
    output_dir = os.path.abspath(sys.argv[2])
    if '--verbose' in sys.argv:
        verbose_logging = True

    build_serverless_tutorial_content(input_dir, output_dir)
