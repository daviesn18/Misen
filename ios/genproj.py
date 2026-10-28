import hashlib, os, sys
root = sys.argv[1]  # .../ios
src = os.path.join(root, "Mise")
def uid(*parts): return hashlib.md5("|".join(parts).encode()).hexdigest()[:24].upper()

# collect swift files grouped by folder
files = {}
catalogs = []
for d, dirs, fs in os.walk(src):
    rel = os.path.relpath(d, src)
    # asset catalogs are one opaque resource each; don't descend into them
    for sub in [x for x in dirs if x.endswith(".xcassets")]:
        catalogs.append(os.path.join(rel, sub) if rel != "." else sub)
    dirs[:] = [x for x in dirs if not x.endswith(".xcassets")]
    for f in sorted(fs):
        if f.endswith(".swift") or f.endswith(".ttf"):
            files.setdefault("" if rel == "." else rel, []).append(f)

o = []  # objects lines by section
sections = {k: [] for k in ["PBXBuildFile","PBXFileReference","PBXFrameworksBuildPhase","PBXGroup","PBXNativeTarget","PBXProject","PBXResourcesBuildPhase","PBXSourcesBuildPhase","XCBuildConfiguration","XCConfigurationList"]}

PRODUCT = uid("product")
MAIN = uid("maingroup"); PRODUCTS = uid("productsgroup"); MISE = uid("group","")
TARGET = uid("target"); PROJECT = uid("project")
SRC_PHASE = uid("sources"); FW_PHASE = uid("frameworks"); RES_PHASE = uid("resources")
PCL = uid("projconfiglist"); TCL = uid("targetconfiglist")
PD, PR, TD, TR = uid("pdebug"), uid("prelease"), uid("tdebug"), uid("trelease")

build_ids = []
res_ids = []
group_children = {}
for folder in sorted(files):
    gid = MISE if folder == "" else uid("group", folder)
    group_children.setdefault(gid, [])
    for f in files[folder]:
        path = os.path.join(folder, f) if folder else f
        fr, bf = uid("file", path), uid("build", path)
        is_font = f.endswith(".ttf")
        ftype = "file" if is_font else "sourcecode.swift"
        phase = "Resources" if is_font else "Sources"
        sections["PBXFileReference"].append(f'\t\t{fr} /* {f} */ = {{isa = PBXFileReference; lastKnownFileType = {ftype}; path = {f}; sourceTree = "<group>"; }};')
        sections["PBXBuildFile"].append(f'\t\t{bf} /* {f} in {phase} */ = {{isa = PBXBuildFile; fileRef = {fr} /* {f} */; }};')
        group_children[gid].append((fr, f))
        (res_ids if is_font else build_ids).append((bf, f))
for path in catalogs:
    folder, name = os.path.split(path)
    gid = MISE if folder == "" else uid("group", folder)
    fr, bf = uid("file", path), uid("build", path)
    sections["PBXFileReference"].append(f'\t\t{fr} /* {name} */ = {{isa = PBXFileReference; lastKnownFileType = folder.assetcatalog; path = {name}; sourceTree = "<group>"; }};')
    sections["PBXBuildFile"].append(f'\t\t{bf} /* {name} in Resources */ = {{isa = PBXBuildFile; fileRef = {fr} /* {name} */; }};')
    group_children.setdefault(gid, []).append((fr, name))
    res_ids.append((bf, name))
sections["PBXFileReference"].append(f'\t\t{PRODUCT} /* Mise.app */ = {{isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = Mise.app; sourceTree = BUILT_PRODUCTS_DIR; }};')

# subgroups listed first inside Mise group
subs = [f for f in sorted(files) if f]
mise_children = [(uid("group", s), s) for s in subs] + group_children.get(MISE, [])
def group(gid, name, children, path=None):
    ch = "".join(f"\n\t\t\t\t{c} /* {n} */," for c, n in children)
    p = f"path = {path}; " if path else ""
    sections["PBXGroup"].append(f'\t\t{gid}{" /* "+name+" */" if name else ""} = {{\n\t\t\tisa = PBXGroup;\n\t\t\tchildren = ({ch}\n\t\t\t);\n\t\t\t{p}sourceTree = "<group>";\n\t\t}};')
group(MAIN, None, [(MISE, "Mise"), (PRODUCTS, "Products")])
group(PRODUCTS, "Products", [(PRODUCT, "Mise.app")]).__class__
sections["PBXGroup"][-1] = sections["PBXGroup"][-1].replace('\t\t\tsourceTree', '\t\t\tname = Products;\n\t\t\tsourceTree')
group(MISE, "Mise", mise_children, "Mise")
for s in subs: group(uid("group", s), s, group_children[uid("group", s)], s)

files_list = "".join(f"\n\t\t\t\t{b} /* {f} in Sources */," for b, f in build_ids)
sections["PBXSourcesBuildPhase"].append(f'\t\t{SRC_PHASE} /* Sources */ = {{\n\t\t\tisa = PBXSourcesBuildPhase;\n\t\t\tbuildActionMask = 2147483647;\n\t\t\tfiles = ({files_list}\n\t\t\t);\n\t\t\trunOnlyForDeploymentPostprocessing = 0;\n\t\t}};')
sections["PBXFrameworksBuildPhase"].append(f'\t\t{FW_PHASE} /* Frameworks */ = {{\n\t\t\tisa = PBXFrameworksBuildPhase;\n\t\t\tbuildActionMask = 2147483647;\n\t\t\tfiles = (\n\t\t\t);\n\t\t\trunOnlyForDeploymentPostprocessing = 0;\n\t\t}};')
res_list = "".join(f"\n\t\t\t\t{b} /* {f} in Resources */," for b, f in res_ids)
sections["PBXResourcesBuildPhase"].append(f'\t\t{RES_PHASE} /* Resources */ = {{\n\t\t\tisa = PBXResourcesBuildPhase;\n\t\t\tbuildActionMask = 2147483647;\n\t\t\tfiles = ({res_list}\n\t\t\t);\n\t\t\trunOnlyForDeploymentPostprocessing = 0;\n\t\t}};')
sections["PBXNativeTarget"].append(f'''\t\t{TARGET} /* Mise */ = {{
\t\t\tisa = PBXNativeTarget;
\t\t\tbuildConfigurationList = {TCL} /* Build configuration list for PBXNativeTarget "Mise" */;
\t\t\tbuildPhases = (
\t\t\t\t{SRC_PHASE} /* Sources */,
\t\t\t\t{FW_PHASE} /* Frameworks */,
\t\t\t\t{RES_PHASE} /* Resources */,
\t\t\t);
\t\t\tbuildRules = (
\t\t\t);
\t\t\tdependencies = (
\t\t\t);
\t\t\tname = Mise;
\t\t\tproductName = Mise;
\t\t\tproductReference = {PRODUCT} /* Mise.app */;
\t\t\tproductType = "com.apple.product-type.application";
\t\t}};''')
sections["PBXProject"].append(f'''\t\t{PROJECT} /* Project object */ = {{
\t\t\tisa = PBXProject;
\t\t\tattributes = {{
\t\t\t\tBuildIndependentTargetsInParallel = 1;
\t\t\t\tLastSwiftUpdateCheck = 1500;
\t\t\t\tLastUpgradeCheck = 1500;
\t\t\t\tTargetAttributes = {{
\t\t\t\t\t{TARGET} = {{
\t\t\t\t\t\tCreatedOnToolsVersion = 15.0;
\t\t\t\t\t}};
\t\t\t\t}};
\t\t\t}};
\t\t\tbuildConfigurationList = {PCL} /* Build configuration list for PBXProject "Mise" */;
\t\t\tcompatibilityVersion = "Xcode 14.0";
\t\t\tdevelopmentRegion = en;
\t\t\thasScannedForEncodings = 0;
\t\t\tknownRegions = (
\t\t\t\ten,
\t\t\t\tBase,
\t\t\t);
\t\t\tmainGroup = {MAIN};
\t\t\tproductRefGroup = {PRODUCTS} /* Products */;
\t\t\tprojectDirPath = "";
\t\t\tprojectRoot = "";
\t\t\ttargets = (
\t\t\t\t{TARGET} /* Mise */,
\t\t\t);
\t\t}};''')

common = {
 "ALWAYS_SEARCH_USER_PATHS": "NO", "CLANG_ANALYZER_NONNULL": "YES", "CLANG_ENABLE_MODULES": "YES", "CLANG_ENABLE_OBJC_ARC": "YES",
 "CLANG_ENABLE_OBJC_WEAK": "YES", "COPY_PHASE_STRIP": "NO", "ENABLE_STRICT_OBJC_MSGSEND": "YES", "ENABLE_USER_SCRIPT_SANDBOXING": "YES",
 "GCC_C_LANGUAGE_STANDARD": "gnu17", "GCC_NO_COMMON_BLOCKS": "YES", "IPHONEOS_DEPLOYMENT_TARGET": "17.0",
 "LOCALIZATION_PREFERS_STRING_CATALOGS": "YES", "SDKROOT": "iphoneos",
}
pdebug = dict(common, **{"DEBUG_INFORMATION_FORMAT": "dwarf", "ENABLE_TESTABILITY": "YES", "GCC_DYNAMIC_NO_PIC": "NO",
 "GCC_OPTIMIZATION_LEVEL": "0", "GCC_PREPROCESSOR_DEFINITIONS": '(\n\t\t\t\t\t"DEBUG=1",\n\t\t\t\t\t"$(inherited)",\n\t\t\t\t)',
 "MTL_ENABLE_DEBUG_INFO": "INCLUDE_SOURCE", "ONLY_ACTIVE_ARCH": "YES", "SWIFT_ACTIVE_COMPILATION_CONDITIONS": '"DEBUG $(inherited)"',
 "SWIFT_OPTIMIZATION_LEVEL": '"-Onone"'})
prelease = dict(common, **{"DEBUG_INFORMATION_FORMAT": '"dwarf-with-dsym"', "ENABLE_NS_ASSERTIONS": "NO", "MTL_ENABLE_DEBUG_INFO": "NO",
 "SWIFT_COMPILATION_MODE": "wholemodule", "VALIDATE_PRODUCT": "YES"})
target = {
 "ASSETCATALOG_COMPILER_APPICON_NAME": "AppIcon", "CODE_SIGN_STYLE": "Automatic", "CURRENT_PROJECT_VERSION": "1", "DEVELOPMENT_TEAM": '""', "ENABLE_PREVIEWS": "YES",
 "GENERATE_INFOPLIST_FILE": "YES", "INFOPLIST_KEY_CFBundleDisplayName": "Misen",
 "INFOPLIST_KEY_LSApplicationCategoryType": '"public.app-category.food-and-drink"',
 "INFOPLIST_KEY_UIApplicationSceneManifest_Generation": "YES", "INFOPLIST_KEY_UIApplicationSupportsIndirectInputEvents": "YES",
 "INFOPLIST_KEY_UILaunchScreen_Generation": "YES",
 "INFOPLIST_KEY_UISupportedInterfaceOrientations_iPad": '"UIInterfaceOrientationPortrait UIInterfaceOrientationPortraitUpsideDown UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight"',
 "INFOPLIST_KEY_UISupportedInterfaceOrientations_iPhone": '"UIInterfaceOrientationPortrait UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight"',
 "IPHONEOS_DEPLOYMENT_TARGET": "17.0", "LD_RUNPATH_SEARCH_PATHS": '(\n\t\t\t\t\t"$(inherited)",\n\t\t\t\t\t"@executable_path/Frameworks",\n\t\t\t\t)',
 "MARKETING_VERSION": "1.0", "PRODUCT_BUNDLE_IDENTIFIER": "com.example.mise", "PRODUCT_NAME": '"$(TARGET_NAME)"',
 "SWIFT_EMIT_LOC_STRINGS": "YES", "SWIFT_VERSION": "5.0", "TARGETED_DEVICE_FAMILY": '"1,2"',
}
def conf(i, name, settings):
    body = "".join(f"\n\t\t\t\t{k} = {v};" for k, v in sorted(settings.items()))
    sections["XCBuildConfiguration"].append(f'\t\t{i} /* {name} */ = {{\n\t\t\tisa = XCBuildConfiguration;\n\t\t\tbuildSettings = {{{body}\n\t\t\t}};\n\t\t\tname = {name};\n\t\t}};')
conf(PD, "Debug", pdebug); conf(PR, "Release", prelease); conf(TD, "Debug", target); conf(TR, "Release", target)
def clist(i, label, d, r):
    sections["XCConfigurationList"].append(f'\t\t{i} /* Build configuration list for {label} */ = {{\n\t\t\tisa = XCConfigurationList;\n\t\t\tbuildConfigurations = (\n\t\t\t\t{d} /* Debug */,\n\t\t\t\t{r} /* Release */,\n\t\t\t);\n\t\t\tdefaultConfigurationIsVisible = 0;\n\t\t\tdefaultConfigurationName = Release;\n\t\t}};')
clist(PCL, 'PBXProject "Mise"', PD, PR); clist(TCL, 'PBXNativeTarget "Mise"', TD, TR)

out = ["// !$*UTF8*$!", "{", "\tarchiveVersion = 1;", "\tclasses = {", "\t};", "\tobjectVersion = 56;", "\tobjects = {", ""]
for k, v in sections.items():
    out += [f"/* Begin {k} section */"] + v + [f"/* End {k} section */", ""]
out += ["\t};", f"\trootObject = {PROJECT} /* Project object */;", "}", ""]
proj = os.path.join(root, "Mise.xcodeproj")
os.makedirs(os.path.join(proj, "project.xcworkspace"), exist_ok=True)
open(os.path.join(proj, "project.pbxproj"), "w").write("\n".join(out))
open(os.path.join(proj, "project.xcworkspace", "contents.xcworkspacedata"), "w").write('<?xml version="1.0" encoding="UTF-8"?>\n<Workspace\n   version = "1.0">\n   <FileRef\n      location = "self:">\n   </FileRef>\n</Workspace>\n')
print("files:", sum(len(v) for v in files.values()))
