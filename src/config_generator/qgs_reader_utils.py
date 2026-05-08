
def element_attr(element, attr, default=None):
    """ Safely queries the attribute of an element which may be none. """
    return element.get(attr, default) if element is not None else default

def element_text(element, default=None):
    """ Safely queries the value of an element which may be none. """
    return element.text if element is not None and element.text is not None else default

def find_maplayer(project, layerid, layername):
    """ Search for maplayer element in project by layerid, or as a fallback by layername. """
    layer = project.find(".//maplayer[id='%s']" % layerid)
    if layer is not None:
        return layer
    # Try to resolve by layer name
    for maplayer in project.findall(".//maplayer"):
        if element_text(maplayer.find("layername")) == layername:
            return layer
    return None
