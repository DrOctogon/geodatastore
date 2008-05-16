import wsgiref.handlers
import xml.dom.minidom
from urllib import urlencode
import traceback
import sys
import exceptions

from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.api import users

class IncorrectUserException(exceptions.Exception):
	def __init__(self):
		return
		
	def __str__(self):
		print "","IncorrectUserException"

class Geometry(db.Model):
  name = db.StringProperty()
  description = db.StringProperty(multiline=True)
  type = db.StringProperty()
  dateModified = db.DateProperty(auto_now=True)
  coordinates = db.ListProperty(db.GeoPt, default=None)
  timeStamp = db.DateProperty(auto_now_add=True)
  altitudes = db.ListProperty(float, default=None)
  userId = db.StringProperty(default=None)
  tags = db.ListProperty(unicode,default=None)
  bboxEast = db.FloatProperty()
  bboxWest = db.FloatProperty()
  bboxSouth = db.FloatProperty()
  bboxNorth = db.FloatProperty()



def getCoordinates(gp):
    lat,lon = 0.0,0.0
    try:
      lat = float(gp.lat)
      lon = float(gp.lon)
    except TypeError, ValueError:
      lat = 0.0
      lon = 0.0
    return lat,lon

def jsonOutput(geometries, operation): 
  geoJson = []
  geoJson.append("{operation: '%s', status: 'success', result:{geometries:{" % operation)
  geoJson.append('records:[')

  points = []
  for geometry in geometries:
    coords = []
    for gp in geometry.coordinates:
    
      lat, lon = getCoordinates(gp)
      coords.append('lat: %s, lng: %s' % (lat, lon))
    altitudes = '[0.0]'
    alt = geometry.altitudes
    bbox = ('{bboxWest: %s, bboxEast: %s, bboxSouth: %s, bboxNorth:%s}' % (geometry.bboxWest,geometry.bboxEast,geometry.bboxSouth,geometry.bboxNorth))
    if alt != []:
      altitudes = '[%s]' % (','.join('%f' % a for a in alt))
    coordinates = '[{%s}]' % ('},{'.join(coords))
    points.append("{key: '%s', userId: '%s', name: '%s', type: '%s', description: '%s', timeStamp: '%s', coordinates: %s, altitudes: %s, bbox: %s}" % (geometry.key(), geometry.userId, geometry.name,geometry.type, geometry.description,geometry.timeStamp, coordinates, altitudes,bbox))

  geoJson.append(','.join(points))
  geoJson.append(']}}}')
  geoJsonOutput = ''.join(geoJson)
  contentType = 'text/javascript'
  return geoJsonOutput, contentType
def createPlacemark(place,geometry,kmlDoc):
  name = kmlDoc.createElement('name')
  textNode = kmlDoc.createTextNode(geometry.name)
  name.appendChild(textNode)
  place.appendChild(name)
  description = kmlDoc.createElement('description')
  textNode = kmlDoc.createTextNode(geometry.description)
  description.appendChild(textNode)
  place.appendChild(description)
  coordString = createCoordinateString(geometry.coordinates,geometry.altitudes)
  coords = kmlDoc.createElement('coordinates')
  coordsText = kmlDoc.createTextNode(coordString)
  coords.appendChild(coordsText)
  if geometry.type == 'point':
    point = kmlDoc.createElement('Point')
    point.appendChild(coords)
    place.appendChild(point)

  elif geometry.type == 'poly':
    polygon = kmlDoc.createElement('Polygon')
    outerBounds = kmlDoc.createElement('outerBoundaryIs')
    polygon.appendChild(outerBounds)
    outerBounds.appendChild(coords)
    place.appendChild(polygon)

  elif geometry.type == 'line':
    line = kmlDoc.createElement('LineString')
    line.appendChild(coords)
    place.appendChild(line)
  return place
  
def kmlOutput(geometries,bboxWest=None,bboxSouth=None,bboxEast=None,bboxNorth=None):
  # This creates the core document.
  kmlDoc = xml.dom.minidom.Document()

  # This creates the root element in the KML namespace.
  kml = kmlDoc.createElementNS('http://earth.google.com/kml/2.2','kml')
  kml.setAttribute('xmlns','http://earth.google.com/kml/2.2')

  # This appends the root element to the document.
  kml = kmlDoc.appendChild(kml)

  # This creates the KML Document element and the styles.
  document = kmlDoc.createElement('Document')
    
  for geometry in geometries:
    createPlace = True
    if bboxWest != None:
      if geometry.bboxWest > bboxWest and  geometry.bboxEast < bboxEast and geometry.bboxNorth < bboxNorth and geometry.bboxSouth > bboxSouth:
        createPlace = True
      else:
        createPlace = False
      if createPlace == True:
        p = kmlDoc.createElement('Placemark')
        place = createPlacemark(p,geometry,kmlDoc)
        p = None
        document.appendChild(place)
    else:
      p = kmlDoc.createElement('Placemark')
      place = createPlacemark(p,geometry,kmlDoc)
      p = None
      document.appendChild(place)
  kml.appendChild(document)
  contentType = 'application/vnd.google-earth.kml+xml' 
  return kmlDoc.toprettyxml(encoding="utf-8"), contentType

def createCoordinateString(gps, alts):
  coordinateString = []
  for gp in gps:
    altIterator = 0
    lat,lon = getCoordinates(gp)
    altitude = 0.0
    try:
      altitude = alts[altIterator]
    except IndexError:
      altitude = 0.00
    coordinateString.append('%s,%s,%s' % (lon, lat, altitude))
    altIterator += 1
  return ' '.join(coordinateString)

def computeBBox(lats,lngs):
  flats = map(float,lats)
  flngs = map(float,lngs)
  west = min(flngs)
  east = max(flngs)
  north = max(flats)
  south = min(flats)

  return west, south, east, north


class Request(webapp.RequestHandler):
  def post(self):
    self.operationPicker()

  def get(self):
    self.operationPicker()

  def operationPicker(self):
      operation = self.request.get('operation')
      out,contentType = '',''
      if operation == 'add':
        out,contentType = self.addGeometries()
      elif operation == 'edit':
        out,contentType = self.editGeometries()
      elif operation == 'delete':
        out,contentType = self.deleteGeometries()
      else:
        out,contentType = self.getGeometries()
      self.response.headers['content-type']= contentType
      self.response.out.write(out)

  def getGeometries(self):
    limit = self.request.get('limit',default_value=10)
    output = self.request.get('output',default_value='json')
    userid = self.request.get('userid',default_value=None)
    
    query = []
    type = self.request.get('type',default_value=None)
    distance = self.request.get('distance',default_value=None)
    bbox = self.request.get('BBOX', default_value=None)
    qryString = ''
    argsString = ''
    if type: 
      query.append("type = '%s'" % type)
    if userid: 
      query.append("userId = '%s'" % userid)

    bboxWest = None
    bboxSouth = None
    bboxEast = None
    bboxNorth = None

    if bbox:
      bboxList = bbox.split(',')
      bboxWest = float(bboxList[0])
      bboxSouth = float(bboxList[1])
      bboxEast = float(bboxList[2])
      bboxNorth = float(bboxList[3])
    qryString = '' 
    if len(query) > 0:
      qryString = 'WHERE %s LIMIT %s' % (' and '.join(query), limit)
    geometries = Geometry.gql(qryString)
    outputAction = {'json': jsonOutput(geometries,'get'),'kml': kmlOutput(geometries,bboxWest,bboxSouth,bboxEast,bboxNorth)}
    outputType = {'json': 'text/json','kml': 'application/vnd.google-earth.kml+xml'}
    out,contentType = outputAction.get(output)
    contentType = outputType.get(output)
    return out,contentType

  def addGeometries(self):
    try:
      lat = self.request.get('lat',allow_multiple=True,default_value=0.0)
      lng = self.request.get('lng',allow_multiple=True,default_value=0.0)
      name = self.request.get('name',default_value = '')
      alts = self.request.get('alt', allow_multiple=True, default_value=0.0)
      tags = self.request.get('tag', allow_multiple=True, default_value=None)
      user = users.GetCurrentUser()
      userid=None
      if user:
        userid=user.email()
      west, south, east, north = computeBBox(lat,lng)
      coords = []
      for i in range(0, len(lat)):
        gp = db.GeoPt(lat[i], lng[i])
        coords.append(gp)
      altitudes = []
      for alt in alts:
        altitudes.append(float(alt))
      description = self.request.get('description')
      type = self.request.get('type',default_value='point')
      gp = Geometry(name=name,description=description,type=type,
                     coordinates=coords,altitudes=altitudes,
                     tags=tags, bboxEast=east, bboxWest=west,
                     bboxSouth=south, bboxNorth=north,userId=userid)

      gp.put()
      gps = []
      gps.append(gp)
      jsonResponse,contentType = jsonOutput(gps,'add')

    except TypeError, ValueError:
      jsonResponse="{error:{type:'add',lat:'%s',lng:'%s'}}" % (lat[0], lng[0])
      contentType = 'text/javascript'
    return jsonResponse,contentType

  def editGeometries(self):
    try:
      user = users.GetCurrentUser()
      userid=None
      if user:
        userid=user.email()
      lat = self.request.get('lat',allow_multiple=True,default_value=0.0)
      lng = self.request.get('lng',allow_multiple=True,default_value=0.0)
      name = self.request.get('name',default_value = '')
      alts = self.request.get('alt', allow_multiple=True, default_value=0.0)
      tags = self.request.get('tag', allow_multiple=True, default_value=None) 
      key = self.request.get('key')
      west, south, east, north = computeBBox(lat,lng)
      coords = []
      for i in range(0, len(lat)):
        gp = db.GeoPt(lat[i], lng[i])
        coords.append(gp)

      description = self.request.get('description')
      type = self.request.get('type',default_value='point')

      gp = Geometry.get(key)
      if gp.userid == userid | user.is_current_user_admin():
        gp.name = name
        gp.description=description
        gp.type=type
        gp.coordinates=coords
        gp.altitudes=alts
        gp.tags=tags
        gp.bboxEast=east
        gp.bboxWest=west
        gp.bboxSouth=south
        gp.bboxNorth=north
        gp.put()
        gps = [gp]
        gps.append(gp) 
      else:
        raise IncorrectUserException

      jsonResponse,contentType = jsonOutput(gps, 'edit')
      
    except TypeError, ValueError, IncorrectUserException:
      jsonResponse="{error:{type:'edit',key:'%s'}}" % self.request.get('key')
      contentType = 'text/javascript'
    return jsonResponse,contentType


  def deleteGeometries(self):
    user = users.GetCurrentUser()
    userid=None
    if user:
      userid=user.email()
    success = "success"

    try:
      if gp.userid == userid | user.is_current_user_admin():
        key = str(self.request.get('key'))
        gp = Geometry.get(key)
        gp.delete()
        jsonResponse = "{operation:'delete',status:'success',key:'%s'}" % key
      else:
        raise IncorrectUserException
    except:
      jsonResponse = "{error:{type:'delete',records:{key:'%s'}}}" % self.request.get('key')
    contentType = 'text/javascript'
    return jsonResponse,contentType

application = webapp.WSGIApplication(
                                     [
                                      ('/gen/request', Request)
                                       ],
                                     debug=True)

wsgiref.handlers.CGIHandler().run(application)
