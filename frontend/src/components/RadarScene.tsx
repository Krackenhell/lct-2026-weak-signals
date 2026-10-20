import { useEffect, useRef, useState } from "react";
import * as T from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

export type SceneKind = "radar" | "papers" | "chip" | "growth" | "network" | "shield";
type Props = { kind?: SceneKind; active?: boolean; paused?: boolean; decorative?: boolean; pointIds?: number[] };
const INDIGO = 0x4f3ff0, CORAL = 0xef4d3c;

function material(color: number, glass = false) {
  return new T.MeshPhysicalMaterial({
    color, roughness: glass ? .24 : .3, metalness: .05, envMapIntensity: .45,
    clearcoat: 1, clearcoatRoughness: .18,
    ...(glass ? { transmission: .55, thickness: .35, ior: 1.4 } : {}),
  });
}
function mesh(g: T.BufferGeometry, m: T.Material, parent: T.Object3D, x = 0, y = 0, z = 0) {
  const obj = new T.Mesh(g, m);
  obj.position.set(x, y, z); obj.castShadow = true; obj.receiveShadow = true;
  parent.add(obj); return obj;
}
function box(parent: T.Object3D, m: T.Material, w: number, h: number, d: number, x = 0, y = 0, z = 0) {
  return mesh(new RoundedBoxGeometry(w, h, d, 3, Math.min(w, h, d) * .18), m, parent, x, y, z);
}
function tube(parent: T.Object3D, points: T.Vector3[], m: T.Material, radius = .025) {
  return mesh(new T.TubeGeometry(new T.CatmullRomCurve3(points), 32, radius, 8, false), m, parent);
}

function object(kind: Exclude<SceneKind, "radar">) {
  const group = new T.Group();
  const white = material(0xffffff), blue = material(INDIGO), coral = material(CORAL), glass = material(0xdedbff, true);
  if (kind === "papers") {
    for (let i = 0; i < 3; i++) {
      const page = new T.Group(); page.position.set(i * .12, i * .22, i * -.06); page.rotation.y = -.15 + i * .13;
      box(page, white, 1.45, .07, 1.8);
      for (let l = 0; l < 4; l++) box(page, l === 0 ? blue : glass, l === 0 ? .85 : 1.05, .015, .06, -.07, .045, -.48 + l * .25);
      group.add(page);
    }
    const magnifier = new T.Group(); magnifier.position.set(.7, .9, .65); magnifier.rotation.x = -.7;
    mesh(new T.TorusGeometry(.35, .065, 12, 48), blue, magnifier);
    mesh(new T.CircleGeometry(.29, 40), glass, magnifier, 0, 0, .015);
    box(magnifier, coral, .11, .52, .12, .27, -.4).rotation.z = .55;
    group.add(magnifier);
    const book = new T.Group(); book.position.set(-.5, -.13, .5); book.rotation.y = -.25;
    box(book, blue, 1.7, .12, .85);
    box(book, white, .76, .11, .78, -.4, .1).rotation.z = .13;
    box(book, white, .76, .11, .78, .4, .1).rotation.z = -.13;
    group.add(book);
  } else if (kind === "chip") {
    box(group, blue, 1.5, .32, 1.5); box(group, glass, .95, .12, .95, 0, .22);
    for (let i = -2; i <= 2; i++) for (const side of [-1, 1]) {
      box(group, white, .12, .1, .4, i * .25, 0, side * .86);
      box(group, white, .4, .1, .12, side * .86, 0, i * .25);
    }
    mesh(new T.OctahedronGeometry(.22), coral, group, 0, .6);
    tube(group, [new T.Vector3(-.4, .3, -.35), new T.Vector3(0, .3, -.35), new T.Vector3(0, .3, 0)], white);
  } else if (kind === "growth") {
    for (let i = 0; i < 3; i++) box(group, i === 0 ? glass : blue, .43, .6 + i * .5, .65, (i - 1) * .63, -.5 + (.6 + i * .5) / 2);
    tube(group, [new T.Vector3(-.9, .6, .5), new T.Vector3(-.2, 1.05, .5), new T.Vector3(.8, 1.8, .5)], coral, .075);
    const arrow = mesh(new T.ConeGeometry(.18, .4, 4), coral, group, .82, 1.8, .5); arrow.rotation.z = -.8;
  } else if (kind === "network") {
    mesh(new T.SphereGeometry(1, 48, 32), glass, group);
    for (let i = 0; i < 4; i++) {
      const ring = mesh(new T.TorusGeometry(1.015, .015, 8, 96), blue, group);
      ring.rotation.y = i * Math.PI / 4;
    }
    for (const y of [-.5, 0, .5]) {
      const ring = mesh(new T.TorusGeometry(Math.sqrt(1 - y * y) * 1.015, .012, 8, 64), blue, group, 0, y);
      ring.rotation.x = Math.PI / 2;
    }
    [[.7,.5,.53],[-.7,.1,.73],[.1,-.55,.84],[.2,.9,-.4]].forEach(([x,y,z]) => mesh(new T.SphereGeometry(.105, 20, 16), coral, group, x, y, z));
  } else {
    const shield = new T.Shape();
    shield.moveTo(-.8,.75); shield.quadraticCurveTo(0,1.2,.8,.75); shield.lineTo(.7,-.2);
    shield.quadraticCurveTo(.5,-.65,0,-.95); shield.quadraticCurveTo(-.65,-.6,-.7,-.2); shield.closePath();
    mesh(new T.ExtrudeGeometry(shield, { depth: .22, bevelEnabled: true, bevelSize: .08, bevelThickness: .08, bevelSegments: 4, steps: 1 }), blue, group);
    const badge = mesh(new T.CylinderGeometry(.55,.55,.18,48), coral, group, .18, -.12, .5);
    badge.rotation.x = Math.PI / 2;
    tube(group, [new T.Vector3(-.08,-.12,.62),new T.Vector3(.12,-.32,.62),new T.Vector3(.48,.12,.62)], white, .055);
  }
  return group;
}

// Stable positions are derived from document IDs, so existing markers never jump
// when a later collector finishes or the bounded feed drops an old item.
export function pointPosition(id: number) {
  const angle = id * 2.399963;
  const radius = .62 + ((id * 37) % 100) / 100 * 1.23;
  return new T.Vector3(Math.cos(angle) * radius, .23, Math.sin(angle) * radius);
}

export default function RadarScene({ kind = "radar", active = false, paused = false, decorative = false, pointIds = [] }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const current = useRef({ active, paused, pointIds });
  current.current = { active, paused, pointIds };
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: T.WebGLRenderer;
    try { renderer = new T.WebGLRenderer({ alpha: true, antialias: true, powerPreference: "low-power" }); }
    catch { setFailed(true); return; }
    // Маленькие иллюстрации — без теней и в обычном разрешении: четыре сцены на главной не должны исчерпать видеопамять
    // слабого ноутбука (в headless-Chrome контекст WebGL терялся).
    const light = kind !== "radar";
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, light ? 1 : 1.75));
    renderer.setClearColor(0xffffff, 0);
    renderer.shadowMap.enabled = !light;
    renderer.shadowMap.type = T.PCFShadowMap;
    renderer.toneMapping = T.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
    // Холст виден только после первого удачного кадра: при сбое WebGL не остаётся «мёртвого» холста.
    renderer.domElement.style.opacity = "0";
    renderer.domElement.style.transition = "opacity .4s ease";
    el.appendChild(renderer.domElement);
    const scene = new T.Scene();
    const pmrem = new T.PMREMGenerator(renderer);
    const room = new RoomEnvironment();
    const environment = pmrem.fromScene(room, .04);
    scene.environment = environment.texture;
    room.dispose(); pmrem.dispose();
    const camera = new T.PerspectiveCamera(kind === "radar" ? 35 : 32, 1, .1, 100);
    camera.position.set(kind === "radar" ? 5.5 : 3.5, kind === "radar" ? 6.6 : 3.3, kind === "radar" ? 9 : 5);
    camera.lookAt(0, kind === "radar" ? .45 : .2, 0);
    scene.add(new T.HemisphereLight(0xffffff, 0xc9c5e9, 1.3));
    const key = new T.DirectionalLight(0xffffff, 2.5);
    key.position.set(-3, 8, 6); key.castShadow = true;
    key.shadow.mapSize.set(light ? 256 : 1024, light ? 256 : 1024); key.shadow.camera.left = -6; key.shadow.camera.right = 6;
    key.shadow.camera.top = 6; key.shadow.camera.bottom = -6; key.shadow.normalBias = .025;
    key.shadow.radius = 4; scene.add(key);
    const fill = new T.DirectionalLight(0xc9c3ff, 1); fill.position.set(4, 3, -4); scene.add(fill);
    const ground = mesh(new T.PlaneGeometry(30,30), new T.ShadowMaterial({ opacity: .06 }), scene, 0, -.68);
    ground.rotation.x = -Math.PI / 2; ground.castShadow = false;
    const world = new T.Group(); scene.add(world);
    const face = new T.Group();
    const floats: T.Object3D[] = [];
    let sweep: T.ShaderMaterial | undefined;
    if (kind === "radar") {
      const white = material(0xf5f5ff), blue = material(INDIGO), coral = material(CORAL), glass = material(0xe8e5ff, true);
      mesh(new T.CylinderGeometry(1.8,1.9,.22,96), white, world, 0, -.46);
      mesh(new T.CylinderGeometry(1.82,1.82,.035,96), blue, world, 0, -.33);
      mesh(new T.CylinderGeometry(.62,.85,.65,64), white, world, 0, -.02);
      face.position.set(0,.85,0); face.rotation.x = .24; world.add(face);
      mesh(new T.CylinderGeometry(2.4,2.27,.32,128), white, face);
      mesh(new T.CylinderGeometry(2.25,2.3,.08,128), glass, face, 0, .17);
      // An emissive display keeps the product's exact indigo under studio lights.
      const screen = new T.MeshBasicMaterial({ color: INDIGO, toneMapped: false });
      mesh(new T.CylinderGeometry(2.14,2.14,.03,128), screen, face, 0, .22);
      const ink = new T.MeshBasicMaterial({ color: 0xc1b8ff, transparent: true, opacity: .46 });
      for (const radius of [.5,1,1.5,2.03]) {
        const ring = mesh(new T.TorusGeometry(radius,.009,8,128), ink, face, 0,.244); ring.rotation.x = Math.PI/2;
      }
      for (let i = 0; i < 60; i++) {
        const a = i * Math.PI / 30;
        const tick = box(face, i % 5 === 0 ? white : ink, .015,.01,i % 5 === 0 ? .11 : .045, Math.sin(a)*2.2,.22,Math.cos(a)*2.2);
        tick.rotation.y = a;
      }
      box(face, ink,4.08,.009,.008,0,.245); box(face,ink,.008,.009,4.08,0,.245);
      sweep = new T.ShaderMaterial({
        transparent: true, depthWrite: false, side: T.DoubleSide,
        uniforms: { time: { value: 0 } },
        vertexShader: "varying vec2 v; void main(){v=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}",
        fragmentShader: `varying vec2 v; uniform float time;
          void main(){vec2 p=v-.5;float r=length(p);float a=mod(atan(p.y,p.x)-time+6.283185,6.283185);
          float beam=pow(max(0.,1.-a/1.45),2.);float line=1.-smoothstep(.0,.025,a);
          gl_FragColor=vec4(.78,.75,1.,(beam*.4+line*.55)*smoothstep(.5,.46,r));}`,
      });
      const beam = mesh(new T.CircleGeometry(2.1,128),sweep,face,0,.258); beam.rotation.x=-Math.PI/2; beam.castShadow=false;
      mesh(new T.SphereGeometry(.09,24,16),white,face,0,.28);
      if (decorative) {
        [2,5,9].forEach(id => { const p=pointPosition(id); mesh(new T.SphereGeometry(.075,24,16),coral,face,p.x,.29,p.z); });
        const papers = object("papers"); papers.scale.setScalar(.48); papers.position.set(2.45,2.1,-.5); papers.rotation.y=-.3; world.add(papers); floats.push(papers);
        const chip = object("chip"); chip.scale.setScalar(.48); chip.position.set(-2.6,1.05,.3); chip.rotation.set(.3,.4,.2); world.add(chip); floats.push(chip);
        [[-2.5,2,-1,.16],[2.7,.1,1,.12],[1.6,2.6,-1.8,.08]].forEach(([x,y,z,r])=>{
          floats.push(mesh(new T.SphereGeometry(r,24,16),coral,world,x,y,z));
        });
      }
      const knob = mesh(new T.CylinderGeometry(.14,.14,.11,32),coral,world,.9,-.28,1.35); knob.rotation.x = .15;
      if (!decorative) world.scale.setScalar(1.27);
    } else {
      const model = object(kind); world.add(model); floats.push(model);
    }
    const sizes = { width: 1, height: 1 };
    const resize = new ResizeObserver(([entry]) => {
      sizes.width = entry.contentRect.width; sizes.height = entry.contentRect.height;
      renderer.setSize(sizes.width, sizes.height); camera.aspect = sizes.width / Math.max(1,sizes.height);
      camera.updateProjectionMatrix();
    }); resize.observe(el);
    let visible = true, raf = 0, last = 0, elapsed = 0;
    const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; }); observer.observe(el);
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    const pointer = { x: 0, y: 0 };
    const move = (e: PointerEvent) => { const rect = el.getBoundingClientRect(); pointer.x=(e.clientX-rect.left)/rect.width-.5; pointer.y=(e.clientY-rect.top)/rect.height-.5; };
    const leave = () => { pointer.x=0; pointer.y=0; };
    el.addEventListener("pointermove",move); el.addEventListener("pointerleave",leave);
    const bases = floats.map(f=>f.position.y);
    const render = (now: number) => {
      raf = requestAnimationFrame(render);
      if (!visible || document.hidden || now-last < 32) return;
      const delta = Math.min((now-last)/1000,.08); last=now;
      if (!reduce.matches && !current.current.paused) elapsed+=delta;
      world.rotation.y += ((reduce.matches || current.current.paused ? 0 : pointer.x*.12)-world.rotation.y)*.05;
      if (sweep) sweep.uniforms.time.value = elapsed*(current.current.active ? .9 : .25);
      floats.forEach((f,i)=>{f.position.y=bases[i]+(reduce.matches ? 0 : Math.sin(elapsed*.7+i)*.06);});
      world.updateMatrixWorld(true);
      const overlay = el.parentElement;
      current.current.pointIds.forEach(id=>{
        const node = overlay?.querySelector<HTMLElement>(`[data-radar-point="${id}"]`);
        if (!node) return;
        const p = face.localToWorld(pointPosition(id)).project(camera);
        node.style.left=`${(p.x*.5+.5)*sizes.width}px`; node.style.top=`${(-p.y*.5+.5)*sizes.height}px`;
      });
      renderer.render(scene,camera);
      if (renderer.domElement.style.opacity !== "1") renderer.domElement.style.opacity = "1";
    }; raf=requestAnimationFrame(render);
    const contextLost = (e: Event) => { e.preventDefault(); cancelAnimationFrame(raf); renderer.domElement.style.display = "none"; setFailed(true); };
    renderer.domElement.addEventListener("webglcontextlost",contextLost);
    return () => {
      cancelAnimationFrame(raf); resize.disconnect(); observer.disconnect();
      el.removeEventListener("pointermove",move); el.removeEventListener("pointerleave",leave);
      renderer.domElement.removeEventListener("webglcontextlost",contextLost);
      const materials = new Set<T.Material>();
      scene.traverse(obj=>{if(obj instanceof T.Mesh){obj.geometry.dispose(); (Array.isArray(obj.material)?obj.material:[obj.material]).forEach(m=>materials.add(m));}});
      materials.forEach(m=>m.dispose()); environment.dispose(); renderer.dispose(); renderer.domElement.remove();
    };
  }, [kind, decorative]);

  return <div ref={host} className={`scene-canvas ${failed ? "scene-fallback" : ""}`} aria-hidden="true">
    {failed && <div className="fallback-disc"><i /><i /><i /><span /></div>}
  </div>;
}
