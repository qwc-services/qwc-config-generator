import re
import urllib.request
from xml.dom.minidom import parseString
from qwc_services_core.cache import ExpiringDict

capabilites_cache = ExpiringDict()


def getChildElement(parent, path):
    for part in path.split("/"):
        for node in parent.childNodes:
            if node.nodeName.split(':')[-1] == part:
                parent = node
                break
        else:
            return None
    return parent

def getFirstElementByTagName(parent, name):
    try:
        return parent.getElementsByTagName(name)[0]
    except:
        return None

def getFirstElementValueByTagName(parent, name):
    try:
        return parent.getElementsByTagName(name)[0].firstChild.nodeValue
    except:
        return ""


def getWmsRequestUrl(WMS_Capabilities, reqType, urlObj):
    try:
        reqUrl = getChildElement(WMS_Capabilities, "Capability/Request/%s/DCPType/HTTP/Get/OnlineResource" % reqType).getAttribute('xlink:href')
        reqUrlObj = urllib.parse.urlparse(reqUrl)
        # Clear scheme to ensure same scheme as viewer is used
        reqUrlObj = reqUrlObj._replace(scheme='')
        params = dict(urllib.parse.parse_qsl(urlObj.query))
        params.update(dict(urllib.parse.parse_qsl(reqUrlObj.query)))
        reqUrlObj = reqUrlObj._replace(query=params)
        return urllib.parse.urlunparse(reqUrlObj)
    except:
        return urllib.parse.urlunparse(urlObj)

def resolve_external_layer(resource, logger, crs=None):
    cpos = resource.find(':')
    hpos = resource.rfind('#')
    if hpos == -1:
        hpos = len(resource) - 1
        urlend = hpos + 1
    else:
        urlend = hpos
    type = resource[0:cpos]
    url = resource[cpos+1:urlend]
    layername = resource[hpos+1:]
    if type == "wms":
        infoFormat = ""
        urlobj = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(urlobj.query))
        if "infoFormat" in params:
            infoFormat = params["infoFormat"]
            del params["infoFormat"]
            urlobj = urlobj._replace(query=urllib.parse.urlencode(params))
            url = urllib.parse.urlunparse(urlobj)

        return get_external_wms_layer(resource, url, layername, infoFormat, logger)
    elif type == "wmts":
        if not crs:
            urlobj = urllib.parse.urlparse(url)
            params = dict(urllib.parse.parse_qsl(urlobj.query))
            crs = params.get('crs', 'EPSG:3857')
        return get_external_wmts_layer(resource, url, layername, crs, logger)
    elif type == "mvt":
        return get_extermal_mvt_layer(resource, url, layername)
    else:
        logger.warn("Unknown external layer: %s" % resource)
        return None

def get_external_wms_layer(resource, url, layerName, infoFormat, logger):

    global capabilites_cache

    urlobj = urllib.parse.urlparse(url)
    params = dict(urllib.parse.parse_qsl(urlobj.query))

    extwmsparams = {}
    version = "1.3.0"
    for key in list(params.keys()):
        # Extract extwms params
        if key.startswith("extwms."):
            extwmsparams[key[7:]] = params[key]
            del params[key]
        if key.lower() == "version":
            version = params[key]
            del params[key]
            params["VERSION"] = version
        # Filter service and request from calledServiceUrl, but keep other parameters (i.e. MAP)
        if key.lower() in ["service", "request"]:
            del params[key]

    urlobj = urlobj._replace(query=urllib.parse.urlencode(params))

    params.update({'SERVICE': 'WMS', 'REQUEST': 'GetCapabilities', 'VERSION': version})
    capUrlObj = urlobj._replace(query=urllib.parse.urlencode(params))
    capabilitiesUrl = urllib.parse.urlunparse(capUrlObj)

    if not capabilites_cache.lookup(capabilitiesUrl):
        try:
            response = urllib.request.urlopen(capabilitiesUrl)
        except:
            logger.warn("Failed to download capabilities for external layer %s" % resource)
            return None

        try:
            capabilitiesXml = response.read()
        except:
            logger.warn("Failed to parse capabilities for external layer %s" % resource)
            return None

        capabilites_cache.set(capabilitiesUrl, capabilitiesXml)
    else:
        capabilitiesXml = capabilites_cache.lookup(capabilitiesUrl)["value"]

    capabilities = parseString(capabilitiesXml)
    contents = getFirstElementByTagName(capabilities, "WMS_Capabilities")
    if not contents:
        contents = getFirstElementByTagName(capabilities, "WMT_MS_Capabilities")

    targetLayer = None
    for layer in contents.getElementsByTagName("Layer"):
        name = getFirstElementValueByTagName(layer, "Name")
        if name == layerName:
            targetLayer = layer
            break

    if not targetLayer:
        logger.warn("Could not find external layer %s in capabilities" % resource)
        return None

    # Info formats
    infoFormats = []
    capability = getFirstElementByTagName(contents, "Capability")
    getFeatureInfo = getFirstElementByTagName(capability, "GetFeatureInfo")
    if getFeatureInfo:
        for format in getFeatureInfo.getElementsByTagName("Format"):
            infoFormats.append(format.firstChild.nodeValue)
    # Prefer specified infoFormat if any
    if infoFormat and infoFormat in infoFormats:
        infoFormats = [infoFormat]

    # Attribution
    attribution = {
        "Title": "",
        "OnlineResource": ""
    }
    attributionEl = getFirstElementByTagName(targetLayer, "Attribution")
    if attributionEl is not None:
        attribution["Title"] = getFirstElementValueByTagName(attributionEl, "Title")
        attribution["OnlineResource"] = getFirstElementByTagName(attributionEl, "OnlineResource").getAttribute('xlink:href')

    # URLs
    getMapUrl = getWmsRequestUrl(contents, "GetMap", urlobj)
    featureInfoUrl = getWmsRequestUrl(contents, "GetFeatureInfo", urlobj)
    legendUrl = getWmsRequestUrl(contents, "sld:GetLegendGraphic", urlobj)

    # BBOX
    boundingBox = getFirstElementByTagName(targetLayer, "BoundingBox")
    if boundingBox is not None:
        bbox = {
            "crs": boundingBox.getAttribute("CRS") or boundingBox.getAttribute("SRS"),
            "bounds": [
                float(boundingBox.getAttribute("minx")),
                float(boundingBox.getAttribute("miny")),
                float(boundingBox.getAttribute("maxx")),
                float(boundingBox.getAttribute("maxy"))
            ]
        }

    return {
        "type": "wms",
        "name": resource,
        "title": getFirstElementValueByTagName(targetLayer, "Title") or layerName,
        "abstract": getFirstElementValueByTagName(targetLayer, "Abstract"),
        "attribution": attribution,
        "url": getMapUrl,
        "featureInfoUrl": featureInfoUrl,
        "legendUrl": legendUrl,
        "version": version,
        "infoFormats": infoFormats,
        "queryable": targetLayer.getAttribute("queryable") == "1",
        "bbox": bbox,
        "extwmsparams": extwmsparams,
        "minScale": getFirstElementValueByTagName(targetLayer, "MinScaleDenominator") or None,
        "maxScale": getFirstElementValueByTagName(targetLayer, "MaxScaleDenominator") or None,
        "params": {
            "LAYERS": layerName
        }
    }


def get_external_wmts_layer(resource, capabilitiesUrl, layerName, crs, logger):

    global capabilites_cache

    if not capabilites_cache.lookup(capabilitiesUrl):
        try:
            response = urllib.request.urlopen(capabilitiesUrl)
        except:
            logger.warn("Failed to download capabilities for external layer %s" % resource)
            return None

        try:
            capabilitiesXml = response.read()
        except:
            logger.warn("Failed to parse capabilities for external layer %s" % resource)
            return None

        capabilites_cache.set(capabilitiesUrl, capabilitiesXml)
    else:
        capabilitiesXml = capabilites_cache.lookup(capabilitiesUrl)["value"]

    capabilities = parseString(capabilitiesXml)
    contents = getFirstElementByTagName(capabilities, "Contents")

    # Search for layer
    targetLayer = None
    for layer in contents.getElementsByTagName("Layer"):
        identifier = getFirstElementValueByTagName(layer, "ows:Identifier")
        if identifier == layerName:
            targetLayer = layer
            break

    if not targetLayer:
        logger.warn("Could not find external layer %s in capabilities" % entry)
        return None

    # Get supported tile matrix
    layerTileMatrixSet = []
    for tileMatrixSetLink in targetLayer.getElementsByTagName("TileMatrixSetLink"):
        layerTileMatrixSet.append(getFirstElementValueByTagName(tileMatrixSetLink, "TileMatrixSet"))

    # Get best tile matrix
    tileMatrix = None
    tileMatrixName = ""
    for child in contents.childNodes:
        if child.nodeName == "TileMatrixSet":
            tileMatrixSet = child
            tileMatrixName = getFirstElementValueByTagName(tileMatrixSet, "ows:Identifier")
            supportedCrs = getFirstElementValueByTagName(tileMatrixSet, "ows:SupportedCRS")
            crsMatch = re.search(r'(EPSG).*:(\d+)', supportedCrs)
            if crsMatch and crs == "EPSG:" + crsMatch.group(2) and tileMatrixName in layerTileMatrixSet:
                tileMatrix = tileMatrixSet.getElementsByTagName("TileMatrix")
                break

    if not tileMatrix:
        logger.warn("Could not find compatible tile matrix for external layer %s" % resource)
        return None

    # Compute origin and resolutions
    origin = list(map(float, filter(bool, getFirstElementValueByTagName(tileMatrix[0], "TopLeftCorner").split(" "))))
    tileSize = [
        int(getFirstElementValueByTagName(tileMatrix[0], "TileWidth")),
        int(getFirstElementValueByTagName(tileMatrix[0], "TileHeight"))
    ]
    resolutions = []
    for entry in tileMatrix:
        scaleDenominator = getFirstElementValueByTagName(entry, "ScaleDenominator")
        # 0.00028: assumed pixel width in meters, as per WMTS standard
        resolutions.append(float(scaleDenominator) * 0.00028)

    # Determine style
    styleIdentifier = ""
    for style in targetLayer.getElementsByTagName("Style"):
        if style.getAttribute("isDefault") == "true":
            styleIdentifier = getFirstElementValueByTagName(style, "ows:Identifier")
            break

    # Resource URL
    tileUrl = None
    for resourceURL in targetLayer.getElementsByTagName("ResourceURL"):
        if resourceURL.getAttribute("resourceType") == "tile":
            tileUrl = resourceURL.getAttribute("template")

    # Dimensions
    for dimension in targetLayer.getElementsByTagName("Dimension"):
        dimensionIdentifier = getFirstElementValueByTagName(dimension, "ows:Identifier")
        dimensionValue = getFirstElementValueByTagName(dimension, "Default")
        tileUrl = tileUrl.replace("{%s}" % dimensionIdentifier, dimensionValue)

    # Title
    title = getFirstElementValueByTagName(targetLayer, "ows:Title")
    if not title:
        title = layerName

    # Abstract
    abstract = getFirstElementValueByTagName(targetLayer, "ows:Abstract")

    # BBox
    bounds = []
    wgs84BoundingBox = getFirstElementByTagName(targetLayer, "ows:WGS84BoundingBox")
    if wgs84BoundingBox is not None:
        lowerCorner = list(map(float, filter(bool, getFirstElementValueByTagName(wgs84BoundingBox,"ows:LowerCorner").split(" "))))
        upperCorner = list(map(float, filter(bool, getFirstElementValueByTagName(wgs84BoundingBox,"ows:UpperCorner").split(" "))))
        bounds = lowerCorner + upperCorner

    # Attribution
    attribution = {}
    serviceProvider = getFirstElementByTagName(capabilities, "ows:ServiceProvider")
    if serviceProvider is not None:
        attribution["Title"] = getFirstElementValueByTagName(serviceProvider, "ows:ProviderName")
        attribution["OnlineResource"] = getFirstElementByTagName(serviceProvider, "ows:ProviderSite").getAttribute('xlink:href')

    # Format
    format = getFirstElementValueByTagName(targetLayer, "Format")

    # RequestEncoding
    requestEncoding = ""
    operationsMetadata = getFirstElementByTagName(capabilities, "ows:OperationsMetadata")
    if operationsMetadata is not None:
        for operation in operationsMetadata.getElementsByTagName("ows:Operation"):
            if operation.getAttribute("name") == "GetCapabilities":
                constraint = getFirstElementByTagName(operation, "ows:Constraint")
                if constraint.getAttribute("name") == "GetEncoding":
                    requestEncoding = getFirstElementValueByTagName(constraint, "ows:Value")

    return {
        "type": "wmts",
        "url": tileUrl,
        "capabilitiesUrl": capabilitiesUrl,
        "title": title,
        "name": resource,
        "format": format,
        "requestEncoding": requestEncoding,
        "tileMatrixPrefix": "",
        "tileMatrixSet": tileMatrixName,
        "originX": origin[0],
        "originY": origin[1],
        "projection": crs,
        "tileSize": tileSize,
        "style": styleIdentifier,
        "bbox": {
            "crs": "EPSG:4326",
            "bounds": bounds
        },
        "resolutions": resolutions,
        "abstract": abstract,
        "attribution": attribution
    }

def get_extermal_mvt_layer(resource, urls, tilegridname):
    url, styleurl = urls.split("|")
    return {
        "name": resource,
        "type": "mvt",
        "url": url,
        "style": styleurl,
        "tileGridName": tilegridname
    }
