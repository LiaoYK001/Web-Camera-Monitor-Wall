import QtQuick
import QtQuick.Controls
import Qt5Compat.GraphicalEffects
import org.freedesktop.gstreamer.Qt6GLVideoItem 1.0

Item {
    id: root
    property var sceneModel
    property bool editMode: true
    property int selectedRow: -1
    property string busLabel: "Preview"
    property bool programBus: false
    property int nestedDepth: 0
    property bool showLabel: true

    Rectangle {
        id: canvas
        anchors.centerIn: parent
        width: Math.min(parent.width, parent.height * sceneModel.canvasWidth / sceneModel.canvasHeight)
        height: width * sceneModel.canvasHeight / sceneModel.canvasWidth
        color: "black"
        clip: true

        Label {
            z: 1000
            visible: root.showLabel
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.margins: 6
            text: root.busLabel + " · " + sceneModel.sceneName
            color: "white"
            background: Rectangle { color: "#aa10141c"; radius: 3 }
            padding: 5
        }

        Repeater {
            model: sceneModel
            delegate: Rectangle {
                required property int index
                required property string kind
                required property string name
                required property real sceneX
                required property real sceneY
                required property real sceneWidth
                required property real sceneHeight
                required property real sceneRotation
                required property real sceneOpacity
                required property bool sceneVisible
                required property bool sceneLocked
                required property int sceneZ
                required property string sourceText
                required property string sourceColor
                required property string sourceFilePath
                required property string cameraId
                required property string profileId
                required property string nestedSceneId
                required property int cropTop
                required property int cropRight
                required property int cropBottom
                required property int cropLeft
                required property var sourceFilters
                property string studioSessionId: ""
                function filterAmount(filterKind, fallback) {
                    for (let filter of sourceFilters) {
                        if (filter.enabled && filter.kind === filterKind)
                            return filter.amount
                    }
                    return fallback
                }
                function filterValue(filterKind, fallback) {
                    for (let filter of sourceFilters) {
                        if (filter.enabled && filter.kind === filterKind)
                            return filter.value
                    }
                    return fallback
                }
                function scalingAspect() {
                    const value = filterValue("scaling", "")
                    const match = /^(\d+)x(\d+)$/.exec(value)
                    return match ? Number(match[1]) / Number(match[2]) : 0
                }
                property real sourceBrightness: Math.max(-1, Math.min(1,
                    filterAmount("color-correction", 0)))
                property string sourceMask: filterValue("mask-blend", "")
                x: sceneX * canvas.width / sceneModel.canvasWidth
                y: sceneY * canvas.height / sceneModel.canvasHeight
                width: sceneWidth * canvas.width / sceneModel.canvasWidth
                height: sceneHeight * canvas.height / sceneModel.canvasHeight
                rotation: sceneRotation
                opacity: sceneOpacity * Math.max(0, Math.min(1, filterAmount("opacity", 1)))
                visible: sceneVisible
                z: sceneZ
                color: kind === "color" ? sourceColor : "#18202b"
                border.color: root.editMode && index === root.selectedRow ? "#ffbf69" :
                              root.editMode && !sceneLocked ? "#46a6ff" : "transparent"
                Item {
                    id: croppedContent
                    clip: true
                    x: cropLeft * parent.width / Math.max(1, sceneWidth)
                    y: cropTop * parent.height / Math.max(1, sceneHeight)
                    width: Math.max(1, parent.width - (cropLeft + cropRight) * parent.width /
                                    Math.max(1, sceneWidth))
                    height: Math.max(1, parent.height - (cropTop + cropBottom) * parent.height /
                                     Math.max(1, sceneHeight))
                    Item {
                        id: maskedContent
                        anchors.fill: parent
                        layer.enabled: sourceMask.length > 0
                        layer.effect: OpacityMask {
                            maskSource: Image {
                                source: sourceMask
                                asynchronous: true
                                fillMode: Image.Stretch
                            }
                        }
                        Item {
                            id: scaledContent
                            anchors.centerIn: parent
                            property real targetAspect: scalingAspect()
                            property real parentAspect: parent.width / Math.max(1, parent.height)
                            width: targetAspect <= 0 || scaleMode === "stretch" ? parent.width :
                                   scaleMode === "cover" ?
                                       (parentAspect > targetAspect ? parent.width : parent.height * targetAspect) :
                                       (parentAspect > targetAspect ? parent.height * targetAspect : parent.width)
                            height: targetAspect <= 0 || scaleMode === "stretch" ? parent.height :
                                    scaleMode === "cover" ?
                                        (parentAspect > targetAspect ? parent.width / targetAspect : parent.height) :
                                        (parentAspect > targetAspect ? parent.height : parent.width / targetAspect)
                            clip: true
                            layer.enabled: Math.abs(sourceBrightness) > 0.0001
                            layer.effect: BrightnessContrast { brightness: sourceBrightness }
                            GstGLVideoItem {
                                id: cameraVideo
                                anchors.fill: parent
                                visible: kind === "camera"
                            }
                            Image {
                                anchors.fill: parent
                                visible: kind === "image"
                                source: sourceFilePath
                                fillMode: scaleMode === "cover" ? Image.PreserveAspectCrop :
                                          scaleMode === "stretch" ? Image.Stretch : Image.PreserveAspectFit
                                asynchronous: true
                            }
                            Text {
                                anchors.centerIn: parent
                                width: parent.width - 8
                                color: kind === "text" ? sourceColor : "white"
                                text: kind === "text" ? sourceText :
                                      kind === "camera" || kind === "image" || kind === "nested" ? "" : name
                                elide: Text.ElideRight
                                horizontalAlignment: Text.AlignHCenter
                            }
                            Loader {
                                anchors.fill: parent
                                active: kind === "nested" && root.nestedDepth < 2
                                sourceComponent: Component {
                                    StudioCanvas {
                                        sceneModel: clientController.studio.sceneModel(nestedSceneId)
                                        editMode: false
                                        programBus: root.programBus
                                        nestedDepth: root.nestedDepth + 1
                                        showLabel: false
                                    }
                                }
                            }
                        }
                    }
                }
                Component.onCompleted: {
                    if (kind === "camera") {
                        studioSessionId = clientController.startStudioCamera(
                            root.programBus, cameraId, profileId)
                        if (studioSessionId.length > 0)
                            clientController.attachStudioStream(
                                root.programBus, studioSessionId, cameraVideo)
                    }
                }
                Component.onDestruction: {
                    if (studioSessionId.length > 0)
                        clientController.removeStudioStream(root.programBus, studioSessionId)
                }
                DragHandler {
                    enabled: root.editMode && !sceneLocked
                    onActiveChanged: if (!active) sceneModel.moveItem(index,
                        parent.x * sceneModel.canvasWidth / canvas.width,
                        parent.y * sceneModel.canvasHeight / canvas.height)
                }
                TapHandler {
                    enabled: root.editMode
                    onTapped: root.selectedRow = index
                }
            }
        }
    }
}
